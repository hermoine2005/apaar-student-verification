import pytest
import sqlite3
from io import BytesIO
from app import app as flask_app
import app as app_module
from werkzeug.security import generate_password_hash
from conftest import login_client
from backend.cases import migrate_legacy_website_cases
from backend.db import get_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "shared-test.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(db_path))
    flask_app.config.update(TESTING=True, SECRET_KEY="test-secret", APAAR_DB_PATH=str(db_path))
    app_module.init_db()
    client = flask_app.test_client()
    login_client(client)
    return client


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200 and response.json["status"] == "ok"


def test_api_and_website_share_student_records(client):
    created = client.post("/api/v1/students", json={
        "student_code": "API-001", "full_name": "Shared Demo Student",
        "course": "Engineering", "email": "shared@example.test",
    })
    assert created.status_code == 201
    api_student_id = created.json["id"]
    assert b"API-001" in client.get("/students?q=API-001").data
    api_edit = client.patch(f"/api/v1/students/{api_student_id}", json={"full_name": "API Updated Student"})
    assert api_edit.status_code == 200
    assert b"API Updated Student" in client.get(f"/students/{api_student_id}").data

    website_created = client.post("/students/new", data={
        "institution_student_id": "WEB-001", "full_name": "Website Student",
        "institution": "MITAOE Demo Campus", "course": "Engineering",
        "semester": "2", "email": "web@example.test", "notes": "Synthetic",
    }, follow_redirects=True)
    assert website_created.status_code == 200
    api_rows = client.get("/api/v1/students").json["items"]
    website_item = next(row for row in api_rows if row["student_code"] == "WEB-001")
    with app_module.connect_db() as db:
        website_row = db.execute("SELECT id FROM students WHERE institution_student_id='WEB-001'").fetchone()
    assert website_item["id"] == str(website_row["id"])
    website_edit = client.post(f"/students/{website_row['id']}/edit", data={
        "institution_student_id": "WEB-001", "full_name": "Website Updated Student",
        "institution": "forged-other-tenant", "course": "Updated Engineering",
        "semester": "2", "email": "web@example.test", "notes": "Synthetic",
    }, follow_redirects=True)
    assert website_edit.status_code == 200
    api_after_edit = next(row for row in client.get("/api/v1/students").json["items"] if row["student_code"] == "WEB-001")
    assert api_after_edit["id"] == str(website_row["id"])
    assert api_after_edit["full_name"] == "Website Updated Student"
    assert api_after_edit["course"] == "Updated Engineering"


def test_api_update_conflict_rolls_back_and_hides_other_tenants(client):
    first = client.post("/api/v1/students", json={"student_code": "UPDATE-1", "full_name": "Update Target"})
    second = client.post("/api/v1/students", json={"student_code": "UPDATE-2", "full_name": "Unique Record"})
    assert first.status_code == second.status_code == 201
    response = client.put(f"/api/v1/students/{second.json['id']}", json={
        "student_code": "UPDATE-1", "full_name": "Should Not Be Saved",
    })
    assert response.status_code == 409
    rows = client.get("/api/v1/students").json["items"]
    target = next(row for row in rows if row["id"] == second.json["id"])
    assert target["student_code"] == "UPDATE-2"
    with app_module.connect_db() as db:
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "isolated-operator", generate_password_hash("TestPassword123!"), "operator", "Isolated Institution",
        ))
    client.post("/logout")
    login_client(client, "isolated-operator", "TestPassword123!")
    hidden = client.put(f"/api/v1/students/{first.json['id']}", json={"full_name": "Unauthorized Edit"})
    assert hidden.status_code == 404


def test_workflow_foreign_key_guards_invalid_student_references(client):
    assert client.get("/api/v1/health").status_code == 200
    with app_module.connect_db() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("""INSERT INTO workflow_cases
                (id,institution_id,student_id,case_type,status,priority,reason,created_by,created_at,updated_at)
                VALUES('bad-case','MITAOE Demo Campus',999999,'review','open','normal','Synthetic reason','admin','now','now')""")
        with pytest.raises(sqlite3.IntegrityError, match="institution not found"):
            db.execute("""INSERT INTO workflow_cases
                (id,institution_id,student_id,case_type,status,priority,reason,created_by,created_at,updated_at)
                VALUES('wrong-tenant-case','Different Campus',1,'review','open','normal','Synthetic reason','admin','now','now')""")
        db.execute("""INSERT INTO workflow_cases
            (id,institution_id,student_id,case_type,status,priority,reason,created_by,created_at,updated_at)
            VALUES('scoped-case','MITAOE Demo Campus',1,'review','open','normal','Synthetic reason','admin','now','now')""")
        with pytest.raises(sqlite3.IntegrityError, match="institution mismatch"):
            db.execute("""INSERT INTO case_events(case_id,institution_id,actor_id,event_type,created_at)
                VALUES('scoped-case','Different Campus','admin','test','now')""")
        with pytest.raises(sqlite3.IntegrityError, match="institution mismatch"):
            db.execute("""INSERT INTO case_evidence
                (id,case_id,institution_id,evidence_type,source,uploaded_by,uploaded_at)
                VALUES('wrong-evidence','scoped-case','Different Campus','synthetic','demo','admin','now')""")


def test_identity_headers_cannot_authenticate_or_select_tenant():
    client = flask_app.test_client()
    forged = {"X-User-Id": "attacker", "X-Institution-Id": "school-a",
              "X-User-Role": "institution_admin"}
    response = client.get("/api/v1/students", headers=forged)
    assert response.status_code == 401


def test_identity_headers_cannot_override_authenticated_tenant(client):
    client.post("/api/v1/students", json={"student_code": "TENANT-1", "full_name": "Demo Tenant"})
    response = client.get("/api/v1/students", headers={
        "X-Institution-Id": "another-school", "X-User-Role": "platform_admin",
    })
    assert response.status_code == 200
    assert all(item["institution_id"] == "MITAOE Demo Campus" for item in response.json["items"])


def test_import_dry_run_does_not_write_shared_records(client):
    before = client.get("/api/v1/students").json["count"]
    response = client.post("/api/v1/imports/dry-run", json={
        "csv_text": "student_code,full_name,email\nCSV-1,Demo Import,import@example.test\n"
    })
    assert response.status_code == 200
    assert response.json["accepted_count"] == 1
    assert client.get("/api/v1/students").json["count"] == before


def test_other_institution_cannot_view_student(client):
    created = client.post("/api/v1/students", json={
        "student_code": "PRIVATE-1", "full_name": "Tenant Private",
    })
    student_id = created.json["id"]
    with app_module.connect_db() as db:
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "other-operator", generate_password_hash("TestPassword123!"),
            "operator", "Other Demo Campus",
        ))
    client.post("/logout")
    login_client(client, "other-operator", "TestPassword123!")
    assert client.get("/api/v1/students").json["count"] == 0
    assert client.get(f"/students/{student_id}").status_code == 302


def test_case_workspace_is_tenant_scoped_and_requires_authentication(client):
    created = client.post("/api/v1/students", json={
        "student_code": "CASE-TENANT-1", "full_name": "Synthetic Case Tenant",
    })
    opened = client.post("/api/v1/verification/cases", json={
        "student_id": created.json["id"], "case_type": "tenant_test",
        "reason": "Synthetic private case for tenant isolation test",
    })
    assert opened.status_code == 201
    client.post("/logout")
    unauthenticated = flask_app.test_client().get("/api/v1/review")
    assert unauthenticated.status_code == 401
    with app_module.connect_db() as db:
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "case-other-tenant", generate_password_hash("TestPassword123!"),
            "operator", "Other Demo Campus",
        ))
    login_client(client, "case-other-tenant", "TestPassword123!")
    page = client.get("/api/v1/review")
    assert page.status_code == 200
    assert b"Synthetic private case for tenant isolation test" not in page.data


def test_review_queue_supports_duplicate_decision_and_case_lifecycle(client):
    page = client.get("/api/v1/review")
    assert page.status_code == 200
    assert b"Possible duplicates" in page.data
    assert b"never merge or delete student records" in page.data
    assert client.post("/api/v1/duplicates/scan").status_code == 302

    with app_module.connect_db() as db:
        candidate = db.execute("SELECT id FROM duplicate_candidates WHERE status='pending_review' LIMIT 1").fetchone()
    assert candidate
    decided = client.post(f"/api/v1/review/candidates/{candidate['id']}/decision", data={
        "decision": "different_people", "note": "Separate synthetic demo identities",
    }, follow_redirects=True)
    assert decided.status_code == 200
    assert b"Duplicate review recorded" in decided.data

    opened = client.post("/api/v1/verification/cases", json={
        "student_id": "1", "case_type": "record_review", "reason": "Check synthetic profile fields",
    })
    assert opened.status_code == 201
    case_id = opened.json["id"]
    moved = client.post(f"/api/v1/review/cases/{case_id}/transition", data={
        "status": "in_review", "note": "Reviewer started the check",
    }, follow_redirects=True)
    assert moved.status_code == 200
    assert b"Case status updated" in moved.data
    assert client.get("/api/v1/audit").json["items"]
    audit_page = client.get("/audit")
    assert audit_page.status_code == 200
    assert b"Review workflow events" in audit_page.data


def test_legacy_website_history_maps_once_to_canonical_case_and_api(client):
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("""INSERT INTO verification_cases
            (student_id,status,summary,findings,source,created_at)
            VALUES(1,'Needs review','Synthetic legacy summary','Synthetic finding',
                   'Synthetic local rules','2026-01-02T03:04:05+00:00')""")
        legacy_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("""INSERT INTO verification_cases
            (student_id,status,summary,findings,source,created_at)
            VALUES(1,'Demo-validated','Synthetic clean result','No local issues',
                   'Synthetic local rules','2026-01-03T03:04:05+00:00')""")
        recorded_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    with flask_app.app_context():
        db = get_db()
        assert migrate_legacy_website_cases(db) == 2
        db.commit()
        assert migrate_legacy_website_cases(db) == 0
        db.commit()
    cases = client.get("/api/v1/verification/cases").json["items"]
    mapped = next(item for item in cases if item["id"] == f"legacy-web:{legacy_id}")
    recorded = next(item for item in cases if item["id"] == f"legacy-web:{recorded_id}")
    assert mapped["status"] == "open"
    assert mapped["legacy_status"] == "Needs review"
    assert mapped["summary"] == "Synthetic legacy summary"
    assert mapped["findings"] == "Synthetic finding"
    assert mapped["created_at"] == "2026-01-02T03:04:05+00:00"
    assert recorded["status"] == "recorded"
    assert recorded["legacy_status"] == "Demo-validated"
    assert b"Synthetic legacy summary" in client.get("/students/1").data
    assert client.get(f"/api/v1/verification/cases/{mapped['id']}/timeline").json["events"][0]["event_type"] == "case.migrated"
    assert client.get("/api/v1/audit/integrity").json["valid"]


def test_legacy_case_migration_rolls_back_on_orphan_reference(client):
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("""INSERT INTO verification_cases
            (student_id,status,summary,findings,source,created_at)
            VALUES(1,'Pending','Valid synthetic row','Finding','Test','2026-01-01')""")
        db.execute("""INSERT INTO verification_cases
            (student_id,status,summary,findings,source,created_at)
            VALUES(999999,'Pending','Orphan synthetic row','Finding','Test','2026-01-01')""")
    with flask_app.app_context():
        db = get_db()
        before_cases = db.execute("SELECT COUNT(*) FROM workflow_cases WHERE legacy_source='website'").fetchone()[0]
        before_events = db.execute("SELECT COUNT(*) FROM case_events WHERE event_type='case.migrated'").fetchone()[0]
        with pytest.raises(ValueError, match="no valid student institution"):
            migrate_legacy_website_cases(db)
        assert db.execute("SELECT COUNT(*) FROM workflow_cases WHERE legacy_source='website'").fetchone()[0] == before_cases
        assert db.execute("SELECT COUNT(*) FROM case_events WHERE event_type='case.migrated'").fetchone()[0] == before_events


def test_case_service_enforces_second_reviewer_and_evidence_timeline(client):
    opened = client.post("/api/v1/verification/cases", json={
        "student_id": "1", "case_type": "record_review", "reason": "Check synthetic record",
    })
    assert opened.status_code == 201
    cid = opened.json["id"]
    added = client.post(f"/api/v1/verification/cases/{cid}/evidence", json={
        "evidence_type": "synthetic note", "source": "demo fixture",
        "description": "Synthetic evidence metadata only", "checksum": "a" * 64,
    })
    assert added.status_code == 201
    evidence_id = added.json["id"]
    started = client.post(f"/api/v1/verification/cases/{cid}/transition", json={
        "status": "in_review", "note": "Reviewer started the review",
    })
    assert started.status_code == 200
    own_close = client.post(f"/api/v1/verification/cases/{cid}/transition", json={
        "status": "resolved", "note": "The creator must not self resolve",
    })
    assert own_close.status_code == 403
    with app_module.connect_db() as db:
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "case-reviewer", generate_password_hash("ReviewerPassword123!"),
            "verifier", "MITAOE Demo Campus",
        ))
    client.post("/logout")
    login_client(client, "case-reviewer", "ReviewerPassword123!")
    decision = client.post(f"/api/v1/verification/evidence/{evidence_id}/decision", json={
        "decision": "accepted", "note": "Synthetic metadata is plausible",
    })
    assert decision.status_code == 200
    resolved = client.post(f"/api/v1/verification/cases/{cid}/transition", json={
        "status": "resolved", "note": "Reviewed synthetic case fields",
    })
    assert resolved.status_code == 200
    timeline = client.get(f"/api/v1/verification/cases/{cid}/timeline").json
    assert [event["event_type"] for event in timeline["events"]] == [
        "case.created", "evidence.added", "case.transitioned", "evidence.reviewed", "case.transitioned",
    ]
    assert timeline["evidence"][0]["review_status"] == "accepted"
    client.post("/logout")
    login_client(client, "admin", "ChangeMe123!")
    assert client.get("/api/v1/audit/integrity").json["valid"]


def test_end_to_end_synthetic_sih_workflow(client):
    # Website create/edit and shared API reads use one student ID.
    created = client.post("/students/new", data={
        "institution_student_id": "SIH-SYN-001", "full_name": "Synthetic SIH Student",
        "institution": "Other Campus Must Be Ignored", "course": "Engineering",
        "semester": "2", "email": "sih@example.test", "notes": "Synthetic demo only",
    }, follow_redirects=True)
    assert created.status_code == 200
    with app_module.connect_db() as db:
        student_id = db.execute("SELECT id FROM students WHERE institution_student_id='SIH-SYN-001'").fetchone()[0]
        assert db.execute("SELECT institution FROM students WHERE id=?", (student_id,)).fetchone()[0] == "MITAOE Demo Campus"
    edited = client.post(f"/students/{student_id}/edit", data={
        "institution_student_id": "SIH-SYN-001", "full_name": "Synthetic SIH Student Edited",
        "institution": "Forged Institution", "course": "Engineering", "semester": "3",
        "email": "sih@example.test", "notes": "Synthetic edit",
    }, follow_redirects=True)
    assert edited.status_code == 200
    api_student = next(row for row in client.get("/api/v1/students").json["items"] if row["id"] == str(student_id))
    assert api_student["full_name"] == "Synthetic SIH Student Edited"

    # Preview includes one invalid row and does not insert either row.
    with app_module.connect_db() as db:
        before_import = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    csv_data = ("institution_student_id,full_name,email,course,semester\n"
                "SIH-CSV-001,Synthetic CSV Student,csv@example.test,Engineering,1\n"
                "SIH-CSV-BAD,Synthetic Invalid Student,not-an-email,Engineering,1\n")
    preview = client.post("/imports", data={
        "file": (BytesIO(csv_data.encode()), "synthetic-sih.csv"),
    }, content_type="multipart/form-data", follow_redirects=True)
    assert preview.status_code == 200 and b"Import preview" in preview.data and b"Email format is invalid" in preview.data
    with app_module.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == before_import
        job_id = db.execute("SELECT id FROM import_jobs WHERE file_name='synthetic-sih.csv'").fetchone()[0]
    committed = client.post(f"/imports/{job_id}/confirm", follow_redirects=True)
    assert committed.status_code == 200 and b"Committed" in committed.data
    assert any(row["student_code"] == "SIH-CSV-001" for row in client.get("/api/v1/students").json["items"])
    assert not any(row["student_code"] == "SIH-CSV-BAD" for row in client.get("/api/v1/students").json["items"])

    # Duplicate signals remain suggestions and require a reviewer decision.
    similar = client.post("/api/v1/students", json={
        "student_code": "SIH-DUP-001", "full_name": "Aarav Sharm",
        "course": "Computer Engineering", "email": "different@example.test",
    })
    assert similar.status_code == 201
    assert client.post("/api/v1/duplicates/scan").status_code == 302
    candidates = client.get("/api/v1/duplicates/candidates").json["items"]
    candidate = next(item for item in candidates if "similar_normalized_name" in item["signals"])
    decision = client.post(f"/api/v1/duplicates/candidates/{candidate['id']}/decision", json={
        "decision": "different_people", "note": "Synthetic records are different people",
    })
    assert decision.status_code == 200

    # A second verifier reviews metadata and resolves the case.
    client.post("/admin/users", data={
        "username": "sih-verifier", "password": "Sih-Demo-Reviewer-Password-44", "role": "verifier",
    })
    opened = client.post("/api/v1/verification/cases", json={
        "student_id": str(student_id), "case_type": "synthetic_demo_review",
        "reason": "Review synthetic student fields for the SIH workflow",
    })
    assert opened.status_code == 201
    case_id = opened.json["id"]
    assert client.post(f"/api/v1/verification/cases/{case_id}/transition", json={
        "status": "in_review", "note": "Begin synthetic review",
    }).status_code == 200
    evidence = client.post(f"/api/v1/verification/cases/{case_id}/evidence", json={
        "evidence_type": "synthetic demo note", "source": "synthetic SIH fixture",
        "description": "Not an official document or provider response",
    })
    assert evidence.status_code == 201 and evidence.json["synthetic_metadata_only"]
    reviewer = flask_app.test_client()
    login_client(reviewer, "sih-verifier", "Sih-Demo-Reviewer-Password-44")
    assert reviewer.post(f"/api/v1/verification/evidence/{evidence.json['id']}/decision", json={
        "decision": "accepted", "note": "Metadata matches this synthetic demo case",
    }).status_code == 200
    assert reviewer.post(f"/api/v1/verification/cases/{case_id}/transition", json={
        "status": "resolved", "note": "Synthetic demo case review completed",
    }).status_code == 200
    assert client.get(f"/api/v1/verification/cases/{case_id}/timeline").json["evidence"][0]["review_status"] == "accepted"

    # Authorized export and audit integrity work; a second tenant cannot read the student.
    assert client.get("/students/export.csv").status_code == 200
    assert client.get("/api/v1/audit/integrity").json["valid"]
    with app_module.connect_db() as db:
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "other-school", generate_password_hash("Other-School-Password-44"),
            "operator", "Other Demo Campus",
        ))
    other = flask_app.test_client()
    login_client(other, "other-school", "Other-School-Password-44")
    assert other.get(f"/api/v1/students/{student_id}").status_code == 404
    assert other.get(f"/students/{student_id}").status_code == 302
    assert other.get(f"/api/v1/verification/cases/{case_id}/timeline").status_code == 404
    assert other.get("/admin/users").status_code == 302


def test_audit_hash_chain_detects_tampering(client):
    created = client.post("/api/v1/students", json={
        "student_code": "AUDIT-001", "full_name": "Audit Test Student",
    })
    assert created.status_code == 201
    integrity = client.get("/api/v1/audit/integrity")
    assert integrity.status_code == 200 and integrity.json["valid"]
    with app_module.connect_db() as db:
        db.execute("UPDATE audit_events SET event_hash='tampered' WHERE institution_id=?", ("MITAOE Demo Campus",))
    integrity = client.get("/api/v1/audit/integrity")
    assert integrity.status_code == 200
    assert integrity.json["valid"] is False
    assert integrity.json["first_invalid_event"] is not None


def test_duplicate_candidates_explain_partial_name_match_without_merging(client):
    before = client.get("/api/v1/students").json["count"]
    created = client.post("/api/v1/students", json={
        "student_code": "DUP-PARTIAL-1", "full_name": "Aarav Sharm",
        "course": "Computer Engineering", "email": "different@example.test",
    })
    assert created.status_code == 201
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT COUNT(*) FROM duplicate_candidates").fetchone()[0] == 0
    csrf_header = client.environ_base.pop("HTTP_X_CSRF_TOKEN")
    assert client.post("/api/v1/duplicates/scan").status_code == 400
    client.environ_base["HTTP_X_CSRF_TOKEN"] = csrf_header
    scanned = client.post("/api/v1/duplicates/scan")
    assert scanned.status_code == 302
    candidates = client.get("/api/v1/duplicates/candidates").json["items"]
    partial = next(item for item in candidates if "similar_normalized_name" in item["signals"])
    assert "same_course" in partial["signals"]
    assert "different_email_addresses" in partial["signals"]
    after = client.get("/api/v1/students").json["count"]
    assert after == before + 1


def test_student_identifiers_are_omitted_from_audit_metadata(client):
    created = client.post("/api/v1/students", json={
        "student_code": "PRIVATE-AUDIT-001", "full_name": "Synthetic Audit Student",
    })
    assert created.status_code == 201
    student_id = int(created.json["id"])
    with sqlite3.connect(app_module.DB_PATH) as db:
        payload = db.execute(
            "SELECT payload_json FROM audit_events WHERE action='student.created' AND entity_id=?",
            (str(student_id),),
        ).fetchone()[0]
    assert "PRIVATE-AUDIT-001" not in payload

    archived = client.post(f"/students/{student_id}/archive")
    assert archived.status_code == 302
    with sqlite3.connect(app_module.DB_PATH) as db:
        details = db.execute(
            "SELECT details FROM audit_logs WHERE action='archive' AND entity_id=?",
            (str(student_id),),
        ).fetchone()[0]
    assert "PRIVATE-AUDIT-001" not in details


def test_case_assignment_is_tenant_scoped_authorized_and_audited(client):
    from conftest import login_client

    opened = client.post("/api/v1/verification/cases", json={
        "student_id": "1", "case_type": "source discrepancy",
        "reason": "Synthetic assignment workflow case",
    })
    assert opened.status_code == 201
    case_id = opened.json["id"]
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "assigned-reviewer", generate_password_hash("ReviewerPassword123!"),
            "verifier", "MITAOE Demo Campus"))
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "second-reviewer", generate_password_hash("SecondReviewerPassword123!"),
            "verifier", "MITAOE Demo Campus"))
        db.execute("INSERT INTO users(username,password_hash,role,institution) VALUES(?,?,?,?)", (
            "other-tenant-reviewer", generate_password_hash("OtherReviewerPassword123!"),
            "verifier", "Other Synthetic Campus"))

    csrf_header = client.environ_base.pop("HTTP_X_CSRF_TOKEN")
    csrf_rejected = client.post(f"/api/v1/review/cases/{case_id}/assignment",
                                data={"assignee": "assigned-reviewer"})
    assert csrf_rejected.status_code == 400
    client.environ_base["HTTP_X_CSRF_TOKEN"] = csrf_header
    assigned = client.post(f"/api/v1/review/cases/{case_id}/assignment",
                           data={"assignee": "assigned-reviewer"})
    assert assigned.status_code == 302
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT assigned_to FROM workflow_cases WHERE id=?", (case_id,)).fetchone()[0] == "assigned-reviewer"
        assert db.execute("SELECT event_type,note FROM case_events WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()[0] == "case.assigned"
        assert db.execute("SELECT count(*) FROM audit_events WHERE action='case.assigned' AND entity_id=?", (case_id,)).fetchone()[0] == 1
    assert b"assigned-reviewer" in client.get("/api/v1/review").data

    rejected = client.post(f"/api/v1/review/cases/{case_id}/assignment",
                           data={"assignee": "other-tenant-reviewer"}, follow_redirects=True)
    assert b"active verifier in this institution" in rejected.data
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT assigned_to FROM workflow_cases WHERE id=?", (case_id,)).fetchone()[0] == "assigned-reviewer"
    reassigned = client.post(f"/api/v1/review/cases/{case_id}/assignment",
                             data={"assignee": "second-reviewer"})
    assert reassigned.status_code == 302
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT assigned_to FROM workflow_cases WHERE id=?", (case_id,)).fetchone()[0] == "second-reviewer"
        assert db.execute("SELECT count(*) FROM case_events WHERE case_id=? AND event_type IN ('case.assigned','case.reassigned')", (case_id,)).fetchone()[0] == 2

    verifier = flask_app.test_client()
    login_client(verifier, "assigned-reviewer", "ReviewerPassword123!")
    forbidden = verifier.post(f"/api/v1/review/cases/{case_id}/assignment",
                              data={"assignee": "assigned-reviewer"})
    assert forbidden.status_code == 403

    verifier.post(f"/api/v1/verification/cases/{case_id}/transition",
                  json={"status": "in_review", "note": "Started independent review"})
    wrong_reviewer = verifier.post(f"/api/v1/verification/cases/{case_id}/transition",
                                   json={"status": "resolved", "note": "Resolved by a non-assignee"})
    assert wrong_reviewer.status_code == 403
    assigned_client = flask_app.test_client()
    login_client(assigned_client, "second-reviewer", "SecondReviewerPassword123!")
    resolved = assigned_client.post(f"/api/v1/verification/cases/{case_id}/transition",
                                    json={"status": "resolved", "note": "Reviewed and corrected synthetic mismatch"})
    assert resolved.status_code == 200
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT status,reviewer_id FROM workflow_cases WHERE id=?", (case_id,)).fetchone() == ("resolved", "second-reviewer")

    administrator = flask_app.test_client()
    login_client(administrator)
    missing = administrator.post("/api/v1/review/cases/not-a-case/assignment",
                                 data={"assignee": "assigned-reviewer"}, follow_redirects=True)
    assert b"not found" in missing.data.lower()
