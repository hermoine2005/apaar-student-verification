import io
import json
import sqlite3

import pytest
from app import app as flask_app
import app as app_module
from backend.source_data import compare_student, parse_source_csv, version_diff
from conftest import login_client
from werkzeug.security import generate_password_hash


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "source-datasets-test.db"
    monkeypatch.setenv("APAAR_DB_PATH", str(db_path))
    app_module.DB_PATH = str(db_path)
    flask_app.config.update(TESTING=True, SECRET_KEY="source-test-secret", APAAR_DB_PATH=str(db_path))
    app_module.init_db()
    from backend.db import init_db as init_backend_db
    with flask_app.app_context():
        init_backend_db()
    client = flask_app.test_client()
    login_client(client)
    return client


def upload(content, dataset="Registrar extract", filename="source.csv"):
    return {"dataset_name": dataset, "file": (io.BytesIO(content), filename)}


def source_id():
    with sqlite3.connect(app_module.DB_PATH) as db:
        return db.execute("SELECT id FROM students WHERE institution='MITAOE Demo Campus' ORDER BY id LIMIT 1").fetchone()[0]


def import_source(client, body, dataset="Registrar extract"):
    response = client.post("/source-datasets", data=upload(body, dataset), follow_redirects=True)
    assert response.status_code == 200
    with sqlite3.connect(app_module.DB_PATH) as db:
        job_id = db.execute("SELECT id FROM institution_source_uploads WHERE institution='MITAOE Demo Campus' ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    return job_id, response


def confirm_source(client, job_id):
    return client.post(f"/source-datasets/{job_id}/confirm", follow_redirects=True)


def test_source_import_preview_confirmation_and_separation(client):
    before = client.get("/api/v1/students").json["count"]
    body = b"institution_student_id,full_name,course,semester,email\nDEMO-1001,Aarav Sharma,Computer Engineering,4,aarav@example.test\n"
    job_id, preview = import_source(client, body)
    assert b"Source import preview" in preview.data
    assert b"No reference records were saved" in preview.data
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT count(*) FROM institution_source_records").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM students").fetchone()[0] == before
    confirmed = confirm_source(client, job_id)
    assert b"saved as version 1" in confirmed.data
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT count(*) FROM institution_source_records").fetchone()[0] == 1
        assert db.execute("SELECT version,status FROM institution_source_uploads WHERE id=?", (job_id,)).fetchone() == (1, "committed")
        assert db.execute("SELECT count(*) FROM audit_events WHERE action='source_dataset.imported'").fetchone()[0] == 1
    repeated = confirm_source(client, job_id)
    assert repeated.status_code == 200
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT count(*) FROM institution_source_records").fetchone()[0] == 1


def test_source_confirmation_rolls_back_dataset_and_records_on_write_failure(client):
    before = client.get("/api/v1/students").json["count"]
    body = b"institution_student_id,full_name\nROLLBACK-SYN-1,Rollback Synthetic\n"
    job_id, _ = import_source(client, body)
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.execute("""CREATE TRIGGER reject_source_record BEFORE INSERT ON institution_source_records
            BEGIN SELECT RAISE(ABORT,'synthetic database write failure'); END""")
    response = confirm_source(client, job_id)
    assert response.status_code == 200 and b"No partial records" in response.data
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT status,dataset_id FROM institution_source_uploads WHERE id=?", (job_id,)).fetchone() == ("preview", None)
        assert db.execute("SELECT count(*) FROM institution_source_datasets").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM institution_source_records").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM students").fetchone()[0] == before


@pytest.mark.parametrize("body,expected", [
    (b"institution_student_id,full_name\n,No ID\n", "required.institution_student_id"),
    (b"institution_student_id,full_name\nDUP-1,First\nDUP-1,Second\n", "duplicate_source_identifier"),
    (b"institution_student_id,full_name\nDUP-1,\"broken\n", "malformed"),
])
def test_source_csv_validation_rejects_bad_or_duplicate_rows(client, body, expected):
    if expected == "malformed":
        rows, errors = parse_source_csv(body)
        assert rows is None and "malformed" in errors[0]
        return
    job_id, response = import_source(client, body)
    assert b"Rejected" in response.data
    with sqlite3.connect(app_module.DB_PATH) as db:
        saved = db.execute("SELECT preview_json FROM institution_source_uploads WHERE id=?", (job_id,)).fetchone()[0]
    assert expected in saved


@pytest.mark.parametrize("raw,expected", [
    (b"", "empty"),
    (b"institution_student_id,full_name,unexpected\nA1,Name,x\n", "unsupported"),
    (b"institution_student_id,full_name,apaar_id\nA1,Name,SYNTHETIC-NOT-USED\n", "unsupported"),
    (b"student_code,full_name\nA1,Name\n", "must include"),
    (b"institution_student_id,full_name\n\xff\n", "utf-8"),
])
def test_source_csv_rejects_invalid_file_shapes(raw, expected):
    rows, errors = parse_source_csv(raw)
    assert rows is None and expected.lower() in errors[0].lower()


def test_source_csv_rejects_oversized_input():
    rows, errors = parse_source_csv(b"institution_student_id,full_name\n" + b"X" * (2 * 1024 * 1024 + 1))
    assert rows is None and "2 MB" in errors[0]


def test_source_csv_enforces_row_limit():
    header = b"institution_student_id,full_name\n"
    rows = b"".join(f"ROW-{index},Synthetic Student\n".encode() for index in range(10001))
    parsed, errors = parse_source_csv(header + rows)
    assert parsed is None and "row limit" in errors[0]


@pytest.mark.parametrize("student,records,outcome", [
    ({"institution_student_id": "X1", "full_name": "Name", "course": "CS", "semester": "1", "email": "a@b.test"},
     [{"institution_student_id": "X1", "full_name": "name", "course": "cs", "semester": "1", "email": "a@b.test"}], "MATCH"),
    ({"institution_student_id": "X1", "full_name": "Name", "course": "CS", "semester": "1", "email": "a@b.test"},
     [{"institution_student_id": "X1", "full_name": "name", "course": "IT", "semester": "1", "email": "a@b.test"}], "MISMATCH"),
    ({"institution_student_id": "X1", "full_name": "Name", "course": "CS", "semester": "1", "email": "a@b.test"},
     [{"institution_student_id": "X2", "full_name": "name", "course": "CS", "semester": "1", "email": "a@b.test"}], "NOT_FOUND"),
    ({"institution_student_id": "X1", "full_name": "Name", "course": "", "semester": "1", "email": "a@b.test"},
     [{"institution_student_id": "X1", "full_name": "name", "course": "CS", "semester": "1", "email": "a@b.test"}], "REVIEW_REQUIRED"),
    ({"institution_student_id": "X1", "full_name": "Name", "course": "CS", "semester": "1", "email": "a@b.test"},
     [{"institution_student_id": "X1", "full_name": "name", "course": "CS", "semester": "1", "email": "a@b.test"}] * 2, "REVIEW_REQUIRED"),
])
def test_source_comparator_outcomes_are_conservative(student, records, outcome):
    result = compare_student(student, records)
    assert result["outcome"] == outcome
    assert result["manual_review_required"] == (outcome in {"MISMATCH", "NOT_FOUND", "REVIEW_REQUIRED"})


def test_comparison_persists_result_case_audit_and_does_not_change_student(client):
    student = source_id()
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute("SELECT * FROM students WHERE id=?", (student,)).fetchone())
        before = tuple(row[key] for key in ("institution_student_id", "full_name", "course", "semester", "status", "updated_at"))
    csv_data = ("institution_student_id,full_name,course,semester,email\n"
                f"{row['institution_student_id']},Different Name,{row['course']},{row['semester']},{row['email']}\n").encode()
    job_id, _ = import_source(client, csv_data)
    confirm_source(client, job_id)
    with sqlite3.connect(app_module.DB_PATH) as db:
        dataset_id = db.execute("SELECT dataset_id FROM institution_source_uploads WHERE id=?", (job_id,)).fetchone()[0]
    detail = client.get(f"/students/{student}")
    token = __import__("re").search(rb'name="csrf_token" value="([^"]+)"', detail.data).group(1).decode()
    result = client.post(f"/students/{student}/compare-source", data={"dataset_id": dataset_id, "csrf_token": token}, follow_redirects=True)
    assert result.status_code == 200
    assert b"MISMATCH" in result.data and b"Institution-provided dataset comparison" in result.data
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.row_factory = sqlite3.Row
        comparison = db.execute("SELECT * FROM institution_source_comparisons WHERE student_id=?", (student,)).fetchone()
        assert comparison["outcome"] == "MISMATCH"
        assert "differed" in comparison["fields_json"]
        assert comparison["run_status"] == "completed"
        assert comparison["ruleset_version"] == "institution-source-comparison-v1"
        assert len(comparison["input_digest"]) == 64
        assert len(comparison["result_digest"]) == 64
        assert json.loads(comparison["outcome_counts_json"]) == {"MISMATCH": 1}
        assert comparison["student_updated_at_snapshot"] == before[-1]
        after = db.execute("SELECT institution_student_id,full_name,course,semester,status,updated_at FROM students WHERE id=?", (student,)).fetchone()
        assert tuple(after) == before
        assert db.execute("SELECT count(*) FROM workflow_cases WHERE student_id=? AND case_type='institution_source_comparison'", (student,)).fetchone()[0] == 1
        audit = db.execute("SELECT payload_json FROM audit_events WHERE action='source_comparison.completed'").fetchone()[0]
        assert 'institution_student_id' not in audit and row["institution_student_id"] not in audit
    assert b"Different Name" not in result.data
    assert b"DEMO-APAAR-0001" not in result.data
    assert b"not official source verification" in result.data.lower()
    api_student = client.get(f"/api/v1/students/{student}").json
    assert api_student["institution_source_comparison"]["dataset_version"] == 1
    assert api_student["institution_source_comparison"]["outcome"] == "MISMATCH"
    assert api_student["institution_source_comparison"]["authoritative"] is False
    assert api_student["institution_source_comparison"]["run_status"] == "completed"
    assert api_student["institution_source_comparison"]["ruleset_version"] == "institution-source-comparison-v1"
    assert api_student["institution_source_comparison"]["stale"] is False
    assert "Comparison provenance" in result.get_data(as_text=True)


def test_source_versions_show_added_removed_changed_and_unchanged_without_raw_values():
    previous = [
        {"institution_student_id": "SYN-KEEP-001", "full_name": "Synthetic Same", "course": "Computing", "semester": "1", "email": "same@example.test"},
        {"institution_student_id": "SYN-EDIT-002", "full_name": "Synthetic Old Name", "course": "Computing", "semester": "1", "email": "old@example.test"},
        {"institution_student_id": "SYN-REMOVE-003", "full_name": "Synthetic Removed", "course": "Arts", "semester": "2", "email": "removed@example.test"},
    ]
    current = [
        {"institution_student_id": "SYN-KEEP-001", "full_name": "Synthetic Same", "course": "Computing", "semester": "1", "email": "same@example.test"},
        {"institution_student_id": "SYN-EDIT-002", "full_name": "Synthetic New Name", "course": "Computing", "semester": "1", "email": "old@example.test"},
        {"institution_student_id": "SYN-ADD-004", "full_name": "Synthetic Added", "course": "Arts", "semester": "2", "email": "new@example.test"},
    ]
    result = version_diff(previous, current)
    assert (result["added_count"], result["removed_count"], result["changed_count"], result["unchanged_count"]) == (1, 1, 1, 1)
    assert result["changed"][0]["fields"] == ["full_name"]
    serialized = json.dumps(result)
    assert "Synthetic New Name" not in serialized and "old@example.test" not in serialized


def test_new_dataset_version_keeps_comparison_on_its_original_version(client):
    student = source_id()
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.row_factory = sqlite3.Row
        student_row = dict(db.execute("SELECT * FROM students WHERE id=?", (student,)).fetchone())
    first = ("institution_student_id,full_name,course,semester,email\n"
             f"{student_row['institution_student_id']},{student_row['full_name']},{student_row['course']},{student_row['semester']},{student_row['email']}\n").encode()
    job1, _ = import_source(client, first, "Immutable Registrar")
    confirm_source(client, job1)
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.row_factory = sqlite3.Row
        dataset_id = db.execute("SELECT dataset_id FROM institution_source_uploads WHERE id=?", (job1,)).fetchone()[0]
    detail = client.get(f"/students/{student}")
    token = __import__("re").search(rb'name="csrf_token" value="([^\"]+)"', detail.data).group(1).decode()
    client.post(f"/students/{student}/compare-source", data={"dataset_id": dataset_id, "csrf_token": token})
    second = ("institution_student_id,full_name,course,semester,email\n"
              f"{student_row['institution_student_id']},{student_row['full_name']},Changed Course,{student_row['semester']},{student_row['email']}\n").encode()
    job2, preview = import_source(client, second, "Immutable Registrar")
    assert b"Changed" in preview.data
    assert confirm_source(client, job2).status_code == 200
    with sqlite3.connect(app_module.DB_PATH) as db:
        old = db.execute("SELECT dataset_version,outcome FROM institution_source_comparisons WHERE student_id=?", (student,)).fetchone()
        versions = db.execute("SELECT version,change_summary_json FROM institution_source_uploads WHERE dataset_id=? AND status='committed' ORDER BY version", (dataset_id,)).fetchall()
        assert old == (1, "MATCH")
        assert [row[0] for row in versions] == [1, 2]
        summary = json.loads(versions[1][1])
        assert summary["changed"][0]["fields"] == ["course"]
        comparison_digest = db.execute("SELECT input_digest FROM institution_source_comparisons WHERE student_id=?", (student,)).fetchone()[0]
        assert comparison_digest == db.execute("SELECT content_hash FROM institution_source_uploads WHERE id=?", (job1,)).fetchone()[0]
    stale_detail = client.get(f"/students/{student}")
    assert b"Stale \xe2\x80\x94 re-run review" in stale_detail.data
    stale_api = client.get(f"/api/v1/students/{student}").json["institution_source_comparison"]
    assert stale_api["stale"] is True
    assert stale_api["dataset_version"] == 1


def test_source_dataset_tenant_and_role_isolation_csrf_and_redaction(client):
    body = b"institution_student_id,full_name,course,semester,email\nSAFE-SYN-900,Safe Synthetic,Computing,1,safe@example.test\n"
    job_id, _ = import_source(client, body)
    with sqlite3.connect(app_module.DB_PATH) as db:
        db.execute("INSERT INTO users(username,password_hash,role,institution,is_active,created_at,updated_at) VALUES(?,?,?,?,1,'now','now')",
                   ("source-auditor", generate_password_hash("AuditorPass123!"), "auditor", "MITAOE Demo Campus"))
        db.execute("INSERT INTO users(username,password_hash,role,institution,is_active,created_at,updated_at) VALUES(?,?,?,?,1,'now','now')",
                   ("source-other", generate_password_hash("OtherPass123!"), "institution_admin", "Other Synthetic Campus"))
        db.execute("INSERT INTO users(username,password_hash,role,institution,is_active,created_at,updated_at) VALUES(?,?,?,?,1,'now','now')",
                   ("source-operator", generate_password_hash("OperatorPass123!"), "operator", "MITAOE Demo Campus"))
    csrf_header = client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)
    no_csrf = client.post(f"/source-datasets/{job_id}/confirm", data={})
    if csrf_header:
        client.environ_base["HTTP_X_CSRF_TOKEN"] = csrf_header
    assert no_csrf.status_code == 400
    auditor = flask_app.test_client()
    login_client(auditor, "source-auditor", "AuditorPass123!")
    assert auditor.get("/source-datasets").status_code in {302, 403}
    operator = flask_app.test_client()
    login_client(operator, "source-operator", "OperatorPass123!")
    assert operator.get("/source-datasets").status_code == 200
    operator_job, _ = import_source(operator,
        b"institution_student_id,full_name\nOPERATOR-SYN-1,Operator Synthetic\n", "Operator Dataset")
    assert confirm_source(operator, operator_job).status_code == 200
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT status FROM institution_source_uploads WHERE id=?", (operator_job,)).fetchone()[0] == "committed"
    other = flask_app.test_client()
    login_client(other, "source-other", "OtherPass123!")
    assert other.get(f"/source-datasets?upload_id={job_id}").status_code == 200
    assert b"SAFE-SYN-900" not in other.get(f"/source-datasets?upload_id={job_id}").data
    assert other.post(f"/source-datasets/{job_id}/confirm", data={"csrf_token": other.environ_base["HTTP_X_CSRF_TOKEN"]}).status_code == 302
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT status FROM institution_source_uploads WHERE id=?", (job_id,)).fetchone()[0] == "preview"
    assert b"SAFE-SYN-900" not in client.get("/api/v1/audit").data


def test_source_upload_schema_upgrade_preserves_existing_preview_and_backs_up(tmp_path, monkeypatch):
    path = tmp_path / "legacy-source.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE institution_source_datasets(id TEXT PRIMARY KEY,institution TEXT NOT NULL,name TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(institution,name));
            CREATE TABLE institution_source_uploads(id TEXT PRIMARY KEY,institution TEXT NOT NULL,dataset_id TEXT,dataset_name TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0,created_by TEXT NOT NULL,file_name TEXT NOT NULL,content_hash TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'preview',preview_json TEXT NOT NULL,accepted_count INTEGER NOT NULL,rejected_count INTEGER NOT NULL,created_at TEXT NOT NULL,confirmed_at TEXT,UNIQUE(institution,content_hash));
            INSERT INTO institution_source_uploads(id,institution,dataset_name,created_by,file_name,content_hash,status,preview_json,accepted_count,rejected_count,created_at)
                VALUES('legacy-job','Synthetic Campus','Legacy Registrar','admin','legacy.csv','hash','preview','[]',0,1,'2026-01-01');
        """)
    monkeypatch.setattr(app_module, "DB_PATH", str(path))
    app_module.backup_before_schema_upgrade()
    backups = list(tmp_path.glob("legacy-source.pre-upgrade-*.db"))
    assert len(backups) == 1
    app_module.init_db()
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(institution_source_uploads)")}
        assert "change_summary_json" in columns
        assert db.execute("SELECT id,change_summary_json FROM institution_source_uploads WHERE id='legacy-job'").fetchone() == ("legacy-job", "{}")
    with sqlite3.connect(backups[0]) as db:
        assert "change_summary_json" not in {row[1] for row in db.execute("PRAGMA table_info(institution_source_uploads)")}
