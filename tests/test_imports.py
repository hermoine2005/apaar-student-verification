import io
import sqlite3

import pytest
from app import app as flask_app
import app as app_module
from backend.db import init_db as init_backend_db
from conftest import login_client


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "imports-test.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(db_path))
    flask_app.config.update(TESTING=True, SECRET_KEY="imports-test-secret", APAAR_DB_PATH=str(db_path))
    app_module.init_db()
    with flask_app.app_context():
        init_backend_db()
    client = flask_app.test_client()
    login_client(client)
    return client


def csv_upload(content):
    return {"file": (io.BytesIO(content.encode("utf-8")), "synthetic-import.csv")}


def test_csv_preview_confirm_history_and_idempotency(client):
    content = (
        "institution_student_id,full_name,institution,email\n"
        "IMPORT-001,Preview Student,Attacker Supplied Campus,preview@example.test\n"
        "IMPORT-002,Second Student,Other Campus,second@example.test\n"
        "IMPORT-002,Repeated Code,Other Campus,repeated@example.test\n"
        ",Missing ID,Other Campus,missing@example.test\n"
    )
    before = client.get("/api/v1/students").json["count"]
    preview = client.post("/imports", data=csv_upload(content), follow_redirects=True)
    assert preview.status_code == 200
    assert b"No student records were written" in preview.data
    assert b"Valid rows" in preview.data and b"Rows with errors" in preview.data
    assert b"incomplete.course" in preview.data and b"Next step:" in preview.data
    assert b"Rows with warnings" in preview.data
    assert b"Preview only: no student records have been written yet." in preview.data
    assert b"Open verification workbench" in preview.data
    with app_module.connect_db() as db:
        job = db.execute("SELECT * FROM import_jobs").fetchone()
        assert job["accepted_count"] == 2 and job["rejected_count"] == 2
        assert db.execute("SELECT count(*) FROM students").fetchone()[0] == before
    errors = client.get(f"/imports/{job['id']}/errors.csv")
    assert errors.status_code == 200 and b"already exists" in errors.data
    assert b"required.institution_student_id" in errors.data

    committed = client.post(f"/imports/{job['id']}/confirm", follow_redirects=True)
    assert committed.status_code == 200 and b"Committed" in committed.data
    assert b"Import confirmed:" in committed.data
    assert b"review the saved student records" in committed.data
    with app_module.connect_db() as db:
        records = db.execute("SELECT institution,full_name FROM students WHERE institution_student_id LIKE 'IMPORT-%' ORDER BY institution_student_id").fetchall()
    assert len(records) == 2
    assert {row["institution"] for row in records} == {"MITAOE Demo Campus"}

    repeated = client.post(f"/imports/{job['id']}/confirm", follow_redirects=True)
    assert repeated.status_code == 200
    assert repeated.data.count(b"Preview Student") >= 1
    with app_module.connect_db() as db:
        assert db.execute("SELECT count(*) FROM students WHERE institution_student_id LIKE 'IMPORT-%'").fetchone()[0] == 2
    duplicate_upload = client.post("/imports", data=csv_upload(content), follow_redirects=True)
    assert duplicate_upload.status_code == 200


def test_import_confirmation_rolls_back_when_data_changes_after_preview(client):
    content = "institution_student_id,full_name\nRACE-001,First Student\nRACE-002,Second Student\n"
    preview = client.post("/imports", data=csv_upload(content), follow_redirects=True)
    with app_module.connect_db() as db:
        job = db.execute("SELECT id FROM import_jobs").fetchone()
        db.execute("""INSERT INTO students(institution_student_id,full_name,institution,created_at,updated_at)
            VALUES('RACE-001','Concurrent Student','MITAOE Demo Campus','now','now')""")
    response = client.post(f"/imports/{job['id']}/confirm", follow_redirects=True)
    assert response.status_code == 200
    assert b"A record changed after preview" in response.data
    with sqlite3.connect(app_module.DB_PATH) as db:
        assert db.execute("SELECT count(*) FROM students WHERE institution_student_id='RACE-002'").fetchone()[0] == 0
