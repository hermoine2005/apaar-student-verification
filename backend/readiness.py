"""Explainable data-readiness scoring for institution-scoped student records."""


def score_student_readiness(record, quality_issues, *, pending_duplicate=False,
                            unresolved_discrepancy=False):
    """Return a derived 0–100 readiness score and concrete ways to improve it.

    The score is an internal data-completeness aid. It does not represent identity
    verification or determine a student's verification status.
    """
    value = lambda key: str(record.get(key) or "").strip()
    deductions = []

    def add(category, field, points, detail, action):
        deductions.append({
            "category": category,
            "field": field,
            "points_lost": points,
            "detail": detail,
            "action": action,
        })

    by_code = {issue["code"]: issue for issue in quality_issues}

    required_fields = (
        ("institution_student_id", "Institutional student ID", 20),
        ("full_name", "Full name", 20),
    )
    for key, label, points in required_fields:
        issue = by_code.get(f"required.{key}")
        if issue:
            add("Required field", label, points, issue["message"], issue["next_action"])

    # Format and length checks share a 30-point budget. Split that deduction
    # across all affected fields so every action has a concrete score impact.
    format_issues = [
        issue for issue in quality_issues
        if issue["severity"] == "error"
        and not issue["code"].startswith("required.")
        and not issue["code"].startswith("duplicate.")
    ]
    if format_issues:
        base_points, extra_points = divmod(30, len(format_issues))
    else:
        base_points, extra_points = 0, 0
    for index, issue in enumerate(format_issues):
        field = issue["code"].split(".", 1)[-1].replace("_", " ").title()
        points = base_points + (1 if index < extra_points else 0)
        add("Valid formats", field, points, issue["message"], issue["next_action"])

    for key, label in (("course", "Course or programme"), ("semester", "Semester")):
        issue = by_code.get(f"incomplete.{key}")
        if issue:
            add("Academic profile", label, 5, issue["message"], issue["next_action"])

    duplicate_issues = [
        issue for issue in quality_issues
        if issue["code"].startswith("duplicate.")
        or issue["code"].startswith("possible_duplicate.")
    ]
    if pending_duplicate or duplicate_issues:
        issue = next((item for item in duplicate_issues if item["code"] == "possible_duplicate.review"), None)
        if issue:
            detail, action = issue["message"], issue["next_action"]
        elif duplicate_issues:
            detail, action = duplicate_issues[0]["message"], duplicate_issues[0]["next_action"]
        else:
            detail = "A possible duplicate candidate is awaiting human review; this is not proof of identity."
            action = "Compare both records in the duplicate-review queue and record a human decision."
        add("Duplicate risk", "Possible duplicate", 10, detail, action)

    if unresolved_discrepancy:
        add(
            "Unresolved discrepancy", "Source comparison", 10,
            "A discrepancy or source-comparison review is still unresolved.",
            "Open the active comparison case, review the differing fields, and record a resolution or request a correction.",
        )

    score = max(0, 100 - sum(item["points_lost"] for item in deductions))
    if score >= 90:
        band = "Ready"
    elif score >= 70:
        band = "Needs attention"
    else:
        band = "Incomplete"

    missing_fields = [
        label for key, label, _ in required_fields
        if not value(key)
    ]
    missing_fields.extend(
        label for key, label in (("course", "Course or programme"), ("semester", "Semester"))
        if not value(key)
    )
    return {
        "score": score,
        "band": band,
        "actions": deductions,
        "missing_fields": missing_fields,
    }
