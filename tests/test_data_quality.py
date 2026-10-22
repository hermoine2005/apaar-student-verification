from backend.data_quality import validate_student_record


def test_student_quality_checks_are_explainable_and_non_mutating():
    record = {
        "institution_student_id": "", "full_name": "Synthetic Student",
        "institution": "Demo Campus", "course": "", "semester": "",
        "email": "not-an-email", "notes": "",
    }
    before = dict(record)
    issues = validate_student_record(record)
    by_code = {issue["code"]: issue for issue in issues}
    assert set(by_code) >= {
        "required.institution_student_id", "format.email",
        "incomplete.course", "incomplete.semester",
    }
    assert all(issue["severity"] in {"error", "warning", "info"} for issue in issues)
    assert all(issue["message"] and issue["next_action"] for issue in issues)
    assert record == before


def test_student_quality_checks_mark_possible_duplicates_as_warnings():
    issues = validate_student_record({
        "institution_student_id": "SYN-101", "full_name": "Synthetic Student",
        "institution": "Demo Campus", "course": "Computing", "semester": "1",
    }, potential_duplicate=True)
    duplicate = next(issue for issue in issues if issue["code"] == "possible_duplicate.review")
    assert duplicate["severity"] == "warning"
    assert "not proof of identity" in duplicate["message"]
