"""Institution supplied reference CSV validation and conservative comparisons."""
import csv
import io
import json
import unicodedata
from collections import Counter
from .data_quality import validate_student_record

MAX_SOURCE_ROWS = 10000
MAX_SOURCE_BYTES = 2 * 1024 * 1024
SOURCE_COMPARISON_RULESET_VERSION = "institution-source-comparison-v1"
REQUIRED_COLUMNS = {"institution_student_id", "full_name"}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | {
    "course",
    "semester",
    "email",
}
COMPARE_FIELDS = ("full_name", "course", "semester", "email")


def parse_source_csv(raw):
    """Validate bounded UTF-8 CSV. Return normalized rows plus safe row findings."""
    if not raw:
        return None, ["The CSV file is empty."]
    if len(raw) > MAX_SOURCE_BYTES:
        return None, ["The source file exceeds the 2 MB limit."]
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return None, ["CSV must use UTF-8 encoding."]
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames or []
        normalized_headers = [str(value or "").strip().lower() for value in headers]
        if len(normalized_headers) != len(set(normalized_headers)):
            return None, ["CSV contains duplicate column headers."]
        if not REQUIRED_COLUMNS.issubset(set(normalized_headers)):
            return None, ["CSV must include institution_student_id and full_name columns."]
        unknown = set(normalized_headers) - ALLOWED_COLUMNS
        if unknown:
            return None, ["CSV contains unsupported columns."]
        rows = []
        for line, raw_row in enumerate(reader, start=2):
            if line > MAX_SOURCE_ROWS + 1:
                return None, [f"CSV exceeds the {MAX_SOURCE_ROWS} row limit."]
            if None in raw_row or any(value is None for value in raw_row.values()):
                rows.append({"line": line, "record": {}, "errors": ["malformed_column_count"], "warnings": []})
                continue
            record = {str(key).strip().lower(): str(value or "").strip() for key, value in raw_row.items()}
            record = {key: record.get(key, "") for key in ALLOWED_COLUMNS}
            quality = validate_student_record(record)
            errors = [issue["code"] for issue in quality if issue["severity"] == "error"]
            warnings = [issue["code"] for issue in quality if issue["severity"] == "warning"]
            rows.append({"line": line, "record": record, "errors": errors, "warnings": warnings})
        counts = Counter(normalize(row["record"].get("institution_student_id")) for row in rows
                         if row["record"].get("institution_student_id"))
        for row in rows:
            code = normalize(row["record"].get("institution_student_id"))
            if code and counts[code] > 1:
                row["errors"].append("duplicate_source_identifier")
        return rows, []
    except csv.Error:
        return None, ["CSV is malformed and could not be parsed."]


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def compare_student(student, source_rows, duplicate_candidate=False):
    """Use institutional ID as the only lookup key; never infer identity by name."""
    key = normalize(student["institution_student_id"])
    if not key:
        return _review("Student has no institutional identifier to use as a comparison key.", {})
    keyed = [row for row in source_rows if normalize(row.get("institution_student_id")) == key]
    if not keyed:
        return {"outcome": "NOT_FOUND", "explanation": "No source row has the same institutional student identifier.",
                "manual_review_required": True, "fields": {}}
    if len(keyed) != 1:
        return _review("Multiple source rows share this institutional identifier; a reviewer must resolve the source data.", {})
    source = keyed[0]
    fields = {}
    missing = []
    for field in COMPARE_FIELDS:
        left, right = normalize(student[field]), normalize(source.get(field))
        if not left or not right:
            fields[field] = "missing"
            missing.append(field)
        else:
            fields[field] = "matched" if left == right else "differed"
    if any(value == "differed" for value in fields.values()):
        return {"outcome": "MISMATCH", "explanation": "One or more compared fields differ; review the source and student records.",
                "manual_review_required": True, "fields": fields}
    if missing:
        return _review("One or more comparison fields are missing; the result is inconclusive and requires human review.", fields)
    if duplicate_candidate:
        return _review("Fields match, but a separate duplicate candidate is pending human review; no identity conclusion is made.", fields)
    return {"outcome": "MATCH", "explanation": "The configured institutional identifier and all compared fields match this institution-provided dataset.",
            "manual_review_required": False, "fields": fields}


def _review(explanation, fields):
    return {"outcome": "REVIEW_REQUIRED", "explanation": explanation,
            "manual_review_required": True, "fields": fields}


def encode_preview(rows):
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def version_diff(previous_rows, candidate_rows):
    """Summarize version changes without retaining raw field values in the report."""
    previous = {normalize(row.get("institution_student_id")): row for row in previous_rows}
    current = {normalize(row.get("institution_student_id")): row for row in candidate_rows}
    added, removed, changed = [], [], []
    unchanged = 0
    for key in sorted(current.keys() - previous.keys()):
        added.append({"identifier": "•••• " + key[-4:]})
    for key in sorted(previous.keys() - current.keys()):
        removed.append({"identifier": "•••• " + key[-4:]})
    for key in sorted(previous.keys() & current.keys()):
        fields = [field for field in COMPARE_FIELDS
                  if normalize(previous[key].get(field)) != normalize(current[key].get(field))]
        if fields:
            changed.append({"identifier": "•••• " + key[-4:], "fields": fields})
        else:
            unchanged += 1
    return {"added_count": len(added), "removed_count": len(removed),
            "changed_count": len(changed), "unchanged_count": unchanged,
            "added": added, "removed": removed, "changed": changed}
