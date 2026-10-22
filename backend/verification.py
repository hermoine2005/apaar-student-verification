"""Versioned local verification rules and explicitly synthetic provider fixtures."""
import json
import os
import uuid
from datetime import datetime, timezone

VERIFICATION_STATUSES = (
    "Draft", "Pending verification", "In progress", "Verified against source",
    "Demo-validated", "Needs review", "Discrepancy detected", "Failed to verify",
    "Expired or stale", "Cancelled",
)
VERIFICATION_TRANSITIONS = {
    "Draft": {"Pending verification", "Cancelled"},
    "Pending verification": {"In progress", "Cancelled"},
    "In progress": {"Verified against source", "Demo-validated", "Needs review", "Discrepancy detected", "Failed to verify", "Expired or stale", "Cancelled"},
    "Needs review": {"In progress", "Demo-validated", "Discrepancy detected", "Failed to verify", "Cancelled"},
    "Discrepancy detected": {"In progress", "Cancelled"},
    "Failed to verify": {"Pending verification", "In progress", "Cancelled"},
    "Expired or stale": {"Pending verification", "In progress", "Cancelled"},
    "Demo-validated": {"In progress", "Cancelled"},
    "Verified against source": {"Expired or stale", "Cancelled"},
    "Cancelled": set(),
}

def validate_transition(current, target, *, authoritative_result=False):
    if target not in VERIFICATION_STATUSES or target not in VERIFICATION_TRANSITIONS.get(current, set()):
        return False
    return target != "Verified against source" or authoritative_result
RULESET_VERSION = "local-rules-1.0"
RULES = (
    ("required_identity_fields", "1.0", "critical", ("institution_student_id", "full_name", "institution")),
    ("academic_fields_present", "1.0", "medium", ("course", "semester")),
    ("email_format", "1.0", "medium", ("email",)),
    ("apaar_identifier_present", "1.0", "low", ("apaar_id",)),
)
MOCK_SCENARIOS = {"matched", "not_found", "mismatch", "inconclusive", "unavailable",
                  "unauthorized", "malformed", "stale"}
PROVIDER_STATES = {"NOT_CONFIGURED", "PENDING", "VERIFIED", "FAILED", "UNAVAILABLE", "SIMULATED"}

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def provider_configuration():
    """Describe configuration without contacting a provider."""
    if os.environ.get("APAAR_PROVIDER", "").strip().lower() != "mock":
        return {"state": "NOT_CONFIGURED", "provider": "none",
                "explanation": "External verification unavailable: no provider configured."}
    if os.environ.get("FLASK_ENV", "").strip().lower() == "production" and os.environ.get("APAAR_ALLOW_MOCK_PROVIDER") != "1":
        return {"state": "UNAVAILABLE", "provider": "none",
                "explanation": "External verification unavailable: synthetic provider is disabled in production mode."}
    return {"state": "SIMULATED", "provider": "synthetic_mock",
            "explanation": "Synthetic mock provider is enabled for local demonstration only."}

def mask_identifier(value):
    value = str(value or "")
    return ("••••" + value[-4:]) if value else "Not associated"

def evaluate_rules(student):
    rules = []
    missing = [field for field in RULES[0][3] if not str(student.get(field) or "").strip()]
    rules.append({"rule_id": RULES[0][0], "rule_version": RULES[0][1], "outcome": "fail" if missing else "pass",
                  "severity": RULES[0][2] if missing else "info",
                  "explanation": "Missing required fields: " + ", ".join(missing) if missing else "Required identity fields are present.",
                  "evidence_refs": [f"student:{student['id']}:field:{field}" for field in RULES[0][3]], "manual_review_required": bool(missing)})
    academic_missing = [field for field in RULES[1][3] if not str(student.get(field) or "").strip()]
    rules.append({"rule_id": RULES[1][0], "rule_version": RULES[1][1], "outcome": "warning" if academic_missing else "pass",
                  "severity": RULES[1][2] if academic_missing else "info",
                  "explanation": "Academic information is incomplete: " + ", ".join(academic_missing) if academic_missing else "Course and semester are present.",
                  "evidence_refs": [f"student:{student['id']}:field:{field}" for field in RULES[1][3]], "manual_review_required": bool(academic_missing)})
    email = str(student.get("email") or "").strip()
    email_bad = bool(email and ("@" not in email or email.startswith("@") or email.endswith("@")))
    rules.append({"rule_id": RULES[2][0], "rule_version": RULES[2][1], "outcome": "fail" if email_bad else "pass",
                  "severity": RULES[2][2] if email_bad else "info", "explanation": "Email format is invalid." if email_bad else "Email is empty or has a basic valid format.",
                  "evidence_refs": [f"student:{student['id']}:field:email"], "manual_review_required": email_bad})
    has_id = bool(str(student.get("apaar_id") or "").strip())
    rules.append({"rule_id": RULES[3][0], "rule_version": RULES[3][1], "outcome": "pass" if has_id else "warning",
                  "severity": "info" if has_id else RULES[3][2], "explanation": "Identifier is present (value redacted)." if has_id else "No identifier is associated; no source lookup can be attempted.",
                  "evidence_refs": [f"student:{student['id']}:field:apaar_id"], "manual_review_required": not has_id})
    return rules

def mock_provider(scenario):
    """Run only the explicitly selected synthetic adapter; never assert authority."""
    configuration = provider_configuration()
    if configuration["state"] != "SIMULATED":
        unavailable_outcome = "not_configured" if configuration["state"] == "NOT_CONFIGURED" else "provider_unavailable"
        return {"provider": configuration["provider"], "state": configuration["state"], "outcome": unavailable_outcome,
                "explanation": configuration["explanation"],
                "manual_review_required": True, "authoritative": False}
    if scenario not in MOCK_SCENARIOS:
        return {"provider": "synthetic_mock", "state": "FAILED", "outcome": "invalid_scenario",
                "explanation": "Synthetic provider scenario is invalid.", "manual_review_required": True, "authoritative": False}
    outcome = {"matched": "match", "not_found": "not_found", "mismatch": "mismatch", "inconclusive": "inconclusive",
               "unavailable": "unavailable", "unauthorized": "unauthorized", "malformed": "malformed", "stale": "stale"}[scenario]
    explanations = {"match": "Synthetic fixture matched; this is not source verification.", "not_found": "Synthetic fixture has no matching record.",
        "mismatch": "Synthetic fixture reports a field mismatch.", "inconclusive": "Synthetic fixture cannot determine a result.",
        "unavailable": "Synthetic provider fixture is unavailable.", "unauthorized": "Synthetic provider fixture returned unauthorized.",
        "malformed": "Synthetic provider fixture returned a malformed response.", "stale": "Synthetic fixture data is stale."}
    return {"provider": configuration["provider"], "state": configuration["state"], "outcome": outcome, "scenario": scenario,
            "explanation": explanations[outcome], "manual_review_required": outcome != "match", "authoritative": False,
            "source_reference": f"synthetic-fixture:{scenario}", "source_timestamp": None}

def persist_result(db, student, institution_id, actor_id, scenario=None):
    rule_results = evaluate_rules(dict(student))
    duplicate = db.execute("""SELECT id,score FROM duplicate_candidates WHERE institution_id=?
        AND status='pending_review' AND (student_a_id=? OR student_b_id=?) ORDER BY score DESC LIMIT 1""",
        (institution_id, student["id"], student["id"])).fetchone()
    if duplicate:
        rule_results.append({"rule_id": "duplicate_candidate_review", "rule_version": "1.0", "outcome": "warning",
            "severity": "medium", "explanation": "A possible duplicate candidate exists; similarity is not an identity decision.",
            "evidence_refs": [f"duplicate_candidate:{duplicate['id']}"], "manual_review_required": True})
    provider = mock_provider(scenario or os.environ.get("APAAR_MOCK_SCENARIO", "matched"))
    failures = [r for r in rule_results if r["outcome"] == "fail"]
    review = any(r["manual_review_required"] for r in rule_results) or provider["manual_review_required"] or provider["outcome"] != "match"
    if failures:
        status, overall = "Needs review", "local_rule_failure"
    elif provider["outcome"] in {"mismatch", "not_found"}:
        status, overall = "Discrepancy detected", provider["outcome"]
    elif provider["outcome"] in {"unavailable", "unauthorized", "malformed"}:
        status, overall = "Failed to verify", provider["outcome"]
    elif provider["outcome"] == "stale":
        status, overall = "Expired or stale", "stale"
    elif review:
        status, overall = "Needs review", provider["outcome"]
    else:
        status, overall = "Demo-validated", "demo_match"
    run_id, stamp = str(uuid.uuid4()), utc_now()
    result = {"outcome": overall, "status": status, "explanation": provider["explanation"],
              "severity": "high" if failures or provider["outcome"] in {"mismatch", "not_found", "unauthorized"} else "info",
              "manual_review_required": bool(review), "provider": provider, "rules": rule_results}
    db.execute("""INSERT INTO verification_runs(id,institution_id,student_id,actor_id,ruleset_version,provider_name,provider_outcome,
        status,overall_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (run_id, institution_id, student["id"], actor_id, RULESET_VERSION, provider["provider"], provider["outcome"], status,
         json.dumps(result, sort_keys=True), stamp))
    for rule in rule_results:
        db.execute("""INSERT INTO verification_rule_results(run_id,institution_id,rule_id,rule_version,outcome,severity,explanation,
            evidence_refs_json,manual_review_required) VALUES(?,?,?,?,?,?,?,?,?)""",
            (run_id, institution_id, rule["rule_id"], rule["rule_version"], rule["outcome"], rule["severity"], rule["explanation"],
             json.dumps(rule["evidence_refs"]), int(rule["manual_review_required"])))
    current = student["status"]
    current = "Pending verification" if current == "Pending" else ("Needs review" if current == "Verified" else current)
    if status != current and not validate_transition(current, status, authoritative_result=provider["authoritative"]):
        if current == "Verified against source":
            current = "Expired or stale"
        if current != "In progress":
            if not validate_transition(current, "In progress"):
                raise ValueError("The current verification state does not permit a new run.")
            current = "In progress"
        if not validate_transition(current, status, authoritative_result=provider["authoritative"]):
            raise ValueError("The verification result is not a permitted next state.")
    db.execute("UPDATE students SET status=?,updated_at=? WHERE id=? AND institution=?", (status, stamp, student["id"], institution_id))
    return run_id, result
