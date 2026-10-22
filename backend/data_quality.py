"""Explainable, non-mutating checks for synthetic student records and imports."""
import re

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_student_record(record, *, duplicate_code=False, duplicate_name=False,
                            duplicate_email=False, potential_duplicate=False):
    """Return stable issue objects without changing or rejecting the supplied record.

    Required fields and length limits mirror the existing CSV/form contract. Course
    and semester are optional in storage but flagged as incomplete for review.
    Email format is a conservative syntax check, not a deliverability check.
    """
    value = lambda key: str(record.get(key) or "").strip()
    issues = []

    def add(code, severity, message, action):
        issues.append({"code": code, "severity": severity, "message": message, "next_action": action})

    code, name = value("institution_student_id"), value("full_name")
    if not code:
        add("required.institution_student_id", "error", "Missing institutional student ID.", "Provide the institution-assigned student ID.")
    elif len(code) > 80:
        add("length.institution_student_id", "error", "Institutional student ID exceeds 80 characters.", "Shorten the value to 80 characters or fewer.")
    elif duplicate_code:
        add("duplicate.institution_student_id", "error", "Institutional student ID already exists.", "Check the existing record before importing.")

    if not name:
        add("required.full_name", "error", "Missing full name.", "Provide the student's recorded full name.")
    elif len(name) > 160:
        add("length.full_name", "error", "Full name exceeds 160 characters.", "Shorten the value to 160 characters or fewer.")

    email = value("email")
    if len(email) > 254 or (email and not _EMAIL.fullmatch(email)):
        add("format.email", "error", "Email format is invalid.", "Check the address format or leave this optional field blank.")

    for field, limit in (("course", 160), ("semester", 40), ("apaar_id", 120), ("notes", 1000)):
        if len(value(field)) > limit:
            add(f"length.{field}", "error", f"{field.replace('_', ' ').title()} exceeds {limit} characters.", f"Shorten {field.replace('_', ' ')} to {limit} characters or fewer.")

    if not value("course"):
        add("incomplete.course", "warning", "Course or programme is not recorded.", "Complete the academic profile if this information is available.")
    if not value("semester"):
        add("incomplete.semester", "warning", "Semester is not recorded.", "Complete the academic profile if this information is available.")
    if duplicate_name:
        add("possible_duplicate.name", "warning", "A similar name exists in this institution; this is not proof of identity.", "Compare records in the human duplicate-review queue.")
    if duplicate_email:
        add("possible_duplicate.email", "warning", "An email address matches another record in this institution.", "Review both records before making a decision.")
    if potential_duplicate:
        add("possible_duplicate.review", "warning", "A potential duplicate candidate is awaiting human review; this is not proof of identity.", "Compare both records in the duplicate-review queue.")
    return issues
