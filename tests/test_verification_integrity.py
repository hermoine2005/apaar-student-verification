import io
import json
import sqlite3
import re
import pytest

import app as app_module
from app import app as flask_app
from conftest import login_client
from backend.verification import MOCK_SCENARIOS, PROVIDER_STATES, VERIFICATION_STATUSES, mock_provider, persist_result, validate_transition


def client_for(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-verification.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(path))
    flask_app.config.update(TESTING=True, SECRET_KEY="synthetic-test-key", APAAR_DB_PATH=str(path))
    app_module.init_db()
    client = flask_app.test_client()
    login_client(client)
    return client


def test_status_transitions_are_closed_and_source_status_needs_trusted_result():
    assert len(VERIFICATION_STATUSES) == 10
    assert not validate_transition("Pending verification", "Verified against source")
    assert validate_transition("In progress", "Verified against source", authoritative_result=True)
    assert not validate_transition("In progress", "arbitrary")


def test_api_cannot_assign_status_and_identifier_is_redacted(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    created = client.post("/api/v1/students", json={"student_code": "REDACT-1", "full_name": "Synthetic Redaction", "course": "Computing", "academic_year": "2"})
    sid = created.json["id"]
    with app_module.connect_db() as db:
        db.execute("UPDATE students SET apaar_id='SYNTHETIC-APAAR-SECRET-9081' WHERE id=?", (sid,))
    rejected = client.patch(f"/api/v1/students/{sid}", json={"verification_status": "Verified against source"})
    assert rejected.status_code == 403
    assert client.get(f"/api/v1/students/{sid}").json["verification_status"] == "Pending verification"
    assert "9081" not in client.get("/api/v1/students").get_data(as_text=True)
    assert "SYNTHETIC-APAAR-SECRET-9081" not in client.get(f"/students/{sid}").get_data(as_text=True)
    assert "SYNTHETIC-APAAR-SECRET-9081" not in client.get("/students/export.csv").get_data(as_text=True)


def test_legacy_verified_is_migrated_to_review_with_audit(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    with app_module.connect_db() as db:
        db.execute("INSERT INTO students(institution_student_id,full_name,institution,status,created_at,updated_at) VALUES('LEGACY-V','Legacy Synthetic','MITAOE Demo Campus','Verified','now','now')")
    app_module.init_db()
    with app_module.connect_db() as db:
        assert db.execute("SELECT status FROM students WHERE institution_student_id='LEGACY-V'").fetchone()[0] == "Needs review"
        assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='legacy_status_migration'").fetchone()[0] == 1


def test_unbacked_demo_status_migrates_and_is_not_counted(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    with app_module.connect_db() as db:
        db.execute("INSERT INTO students(institution_student_id,full_name,institution,status,created_at,updated_at) VALUES('UNBACKED-DEMO','Synthetic Legacy Demo','MITAOE Demo Campus','Demo-validated','now','now')")
        db.execute("DELETE FROM app_migrations WHERE name='verification_status_provenance_v1'")
    app_module.init_db()
    with app_module.connect_db() as db:
        assert db.execute("SELECT status FROM students WHERE institution_student_id='UNBACKED-DEMO'").fetchone()[0] == "Needs review"
    dashboard = client.get("/")
    match = re.search(rb"<span>Demo-validated</span>.*?<strong>(\d+)</strong>", dashboard.data, re.S)
    assert match and int(match.group(1)) == 0


def test_mock_scenario_persists_versioned_structured_result_without_authority(tmp_path, monkeypatch):
    monkeypatch.setenv("APAAR_PROVIDER", "mock")
    client = client_for(tmp_path, monkeypatch)
    created = client.post("/api/v1/students", json={"student_code": "MOCK-1", "full_name": "Synthetic Provider Student", "course": "Computing", "academic_year": "2"})
    sid = created.json["id"]
    with app_module.connect_db() as db:
        db.execute("UPDATE students SET apaar_id='SYNTHETIC-001' WHERE id=?", (sid,))
    response = client.post(f"/students/{sid}/verify", data={
        "mock_scenario": "matched", "csrf_token": client.environ_base["HTTP_X_CSRF_TOKEN"],
    })
    assert response.status_code == 302
    with app_module.connect_db() as db:
        run = db.execute("SELECT * FROM verification_runs WHERE student_id=?", (sid,)).fetchone()
        rules = db.execute("SELECT * FROM verification_rule_results WHERE run_id=?", (run["id"],)).fetchall()
    result = json.loads(run["overall_json"])
    assert run["ruleset_version"] == "local-rules-1.0"
    assert run["provider_name"] == "synthetic_mock"
    assert result["status"] == "Demo-validated"
    assert result["provider"]["authoritative"] is False
    assert result["provider"]["state"] == "SIMULATED"
    assert result["provider"]["source_reference"] == "synthetic-fixture:matched"
    assert len(rules) == 4
    assert MOCK_SCENARIOS == {"matched", "not_found", "mismatch", "inconclusive", "unavailable", "unauthorized", "malformed", "stale"}
    api_result = client.get(f"/api/v1/students/{sid}").json["external_provider_verification"]
    assert api_result["state"] == "SIMULATED" and api_result["authoritative"] is False


@pytest.mark.parametrize(("scenario", "expected"), [
    ("matched", "Demo-validated"), ("not_found", "Discrepancy detected"),
    ("mismatch", "Discrepancy detected"), ("inconclusive", "Needs review"),
    ("unavailable", "Failed to verify"), ("unauthorized", "Failed to verify"),
    ("malformed", "Failed to verify"), ("stale", "Expired or stale"),
])
def test_every_mock_outcome_maps_to_non_authoritative_status(monkeypatch, scenario, expected):
    monkeypatch.setenv("APAAR_PROVIDER", "mock")
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE verification_runs(id TEXT PRIMARY KEY,institution_id TEXT,student_id INTEGER,actor_id TEXT,ruleset_version TEXT,provider_name TEXT,provider_outcome TEXT,status TEXT,overall_json TEXT,created_at TEXT);
        CREATE TABLE verification_rule_results(id INTEGER PRIMARY KEY,run_id TEXT,institution_id TEXT,rule_id TEXT,rule_version TEXT,outcome TEXT,severity TEXT,explanation TEXT,evidence_refs_json TEXT,manual_review_required INTEGER);
        CREATE TABLE duplicate_candidates(id TEXT,institution_id TEXT,student_a_id INTEGER,student_b_id INTEGER,score INTEGER,status TEXT);
        CREATE TABLE students(id INTEGER,status TEXT,updated_at TEXT,institution TEXT);
        INSERT INTO students(id,status,institution) VALUES(1,'Pending verification','Synthetic Institution');
    """)
    student = {"id": 1, "status": "Pending verification", "institution_student_id": "SYN-1", "full_name": "Synthetic Student", "institution": "Synthetic Institution",
               "course": "Computing", "semester": "2", "email": "student@example.test", "apaar_id": "SYNTHETIC-ID"}
    _, result = persist_result(db, student, "Synthetic Institution", "tester", scenario)
    assert result["status"] == expected
    assert result["provider"]["authoritative"] is False
    assert "SYNTHETIC-ID" not in json.dumps(result)
    assert result["provider"]["state"] == "SIMULATED"


def test_missing_provider_is_explicit_and_never_claims_verification(monkeypatch):
    monkeypatch.delenv("APAAR_PROVIDER", raising=False)
    provider = mock_provider("matched")
    assert provider["state"] == "NOT_CONFIGURED"
    assert "no provider configured" in provider["explanation"].lower()
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE verification_runs(id TEXT PRIMARY KEY,institution_id TEXT,student_id INTEGER,actor_id TEXT,ruleset_version TEXT,provider_name TEXT,provider_outcome TEXT,status TEXT,overall_json TEXT,created_at TEXT);
        CREATE TABLE verification_rule_results(id INTEGER PRIMARY KEY,run_id TEXT,institution_id TEXT,rule_id TEXT,rule_version TEXT,outcome TEXT,severity TEXT,explanation TEXT,evidence_refs_json TEXT,manual_review_required INTEGER);
        CREATE TABLE duplicate_candidates(id TEXT,institution_id TEXT,student_a_id INTEGER,student_b_id INTEGER,score INTEGER,status TEXT);
        CREATE TABLE students(id INTEGER,status TEXT,updated_at TEXT,institution TEXT);
        INSERT INTO students(id,status,institution) VALUES(1,'Pending verification','Synthetic Institution');
    """)
    student = {"id": 1, "status": "Pending verification", "institution_student_id": "SYN-1", "full_name": "Synthetic Student", "institution": "Synthetic Institution",
               "course": "Computing", "semester": "2", "email": "student@example.test", "apaar_id": "SYNTHETIC-ID"}
    _, result = persist_result(db, student, "Synthetic Institution", "tester")
    assert result["provider"]["state"] == "NOT_CONFIGURED"
    assert result["status"] == "Needs review"
    assert result["manual_review_required"] is True
    assert result["provider"]["authoritative"] is False
    assert "Verified against source" != result["status"]
    assert PROVIDER_STATES == {"NOT_CONFIGURED", "PENDING", "VERIFIED", "FAILED", "UNAVAILABLE", "SIMULATED"}


def test_missing_provider_state_is_clear_in_ui_and_api_while_local_flow_works(tmp_path, monkeypatch):
    monkeypatch.delenv("APAAR_PROVIDER", raising=False)
    client = client_for(tmp_path, monkeypatch)
    sid = 1
    page = client.get(f"/students/{sid}")
    assert b"NOT_CONFIGURED" in page.data and b"External verification unavailable: no provider configured" in page.data
    response = client.post(f"/students/{sid}/verify", data={
        "mock_scenario": "matched", "csrf_token": client.environ_base["HTTP_X_CSRF_TOKEN"],
    }, follow_redirects=True)
    assert response.status_code == 200 and b"no provider configured" in response.data.lower()
    with app_module.connect_db() as db:
        assert db.execute("SELECT status FROM students WHERE id=?", (sid,)).fetchone()[0] == "Needs review"
    api = client.get(f"/api/v1/students/{sid}").json
    assert api["external_provider_verification"]["state"] == "NOT_CONFIGURED"
    assert api["external_provider_verification"]["authoritative"] is False
    source_csv = b"institution_student_id,full_name,course,semester,email\nDEMO-1001,Aarav Sharma,Computer Engineering,4,aarav@example.test\n"
    uploaded = client.post("/source-datasets", data={"dataset_name": "Synthetic Independent Source",
        "file": (io.BytesIO(source_csv), "independent-source.csv")}, follow_redirects=True)
    assert uploaded.status_code == 200
    with app_module.connect_db() as db:
        upload_id = db.execute("SELECT id FROM institution_source_uploads ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    client.post(f"/source-datasets/{upload_id}/confirm", data={"csrf_token": client.environ_base["HTTP_X_CSRF_TOKEN"]})
    with app_module.connect_db() as db:
        dataset_id = db.execute("SELECT dataset_id FROM institution_source_uploads WHERE id=?", (upload_id,)).fetchone()[0]
    compared = client.post(f"/students/{sid}/compare-source", data={"dataset_id": dataset_id,
        "csrf_token": client.environ_base["HTTP_X_CSRF_TOKEN"]}, follow_redirects=True)
    assert compared.status_code == 200 and b"MATCH" in compared.data
    api_after_comparison = client.get(f"/api/v1/students/{sid}").json
    assert api_after_comparison["external_provider_verification"]["state"] == "NOT_CONFIGURED"
    assert api_after_comparison["institution_source_comparison"]["outcome"] == "MATCH"


def test_mock_provider_is_disabled_in_production_without_explicit_override(monkeypatch):
    monkeypatch.setenv("APAAR_PROVIDER", "mock")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("APAAR_ALLOW_MOCK_PROVIDER", raising=False)
    result = mock_provider("matched")
    assert result["state"] == "UNAVAILABLE"
    assert result["authoritative"] is False

