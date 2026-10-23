r"""Synthetic source dataset timing harness (not collected by pytest).

Run from the repository root with:
    .\.venv\Scripts\python.exe tests\benchmark_source_datasets.py
All database writes target a fresh temporary SQLite file.
"""
import csv
import gc
import io
import os
import platform
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def timed(call):
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def csv_bytes(count, *, version=1):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["institution_student_id", "full_name", "course", "semester", "email"])
    for index in range(count):
        course = "Applied Computing" if version == 1 or index % 100 else "Data Systems"
        writer.writerow([f"BENCH-{count}-{index:05d}", f"Synthetic Learner {index:05d}", course, "2", f"learner{index}@example.test"])
    if version == 2:
        writer.writerow([f"BENCH-{count}-ADDED", "Synthetic Added Learner", "Applied Computing", "2", "added@example.test"])
    return output.getvalue().encode("utf-8")


def main():
    temp = tempfile.TemporaryDirectory(prefix="apaar-source-benchmark-")
    db_path = Path(temp.name) / "benchmark.sqlite"
    os.environ["APAAR_DB_PATH"] = str(db_path)
    os.environ["SECRET_KEY"] = "synthetic-benchmark-secret-key"
    demo_password = "SyntheticBenchmarkOnly123!"
    os.environ["DEMO_ADMIN_PASSWORD"] = demo_password
    os.environ.pop("APAAR_PROVIDER", None)

    from app import app as flask_app
    import app as app_module
    from backend.source_data import parse_source_csv, compare_student, version_diff
    from conftest import login_client

    flask_app.config.update(TESTING=True, SECRET_KEY=os.environ["SECRET_KEY"], APAAR_DB_PATH=str(db_path))
    app_module.DB_PATH = str(db_path)
    client = flask_app.test_client()
    login_client(client, password=demo_password)

    print(f"Python: {platform.python_version()} | SQLite: {sqlite3.sqlite_version} | OS: {platform.platform()}")
    print("Measurements are elapsed wall seconds on one fresh temporary SQLite database; no SLA is implied.")
    for count in (1000, 4000, 8000):
        body = csv_bytes(count)
        parsed, validation_seconds = timed(lambda: parse_source_csv(body))
        rows, parse_errors = parsed
        if parse_errors or rows is None:
            raise RuntimeError(f"synthetic parser rejected the {count} row benchmark fixture")

        dataset_name = f"Synthetic benchmark {count}"
        upload_response, import_seconds = timed(lambda: client.post("/source-datasets", data={
            "dataset_name": dataset_name,
            "file": (io.BytesIO(body), f"bench-{count}.csv"),
        }))
        if upload_response.status_code != 302:
            raise RuntimeError(f"{count} row source preview failed with HTTP {upload_response.status_code}")
        preview_url = upload_response.headers["Location"]
        _, preview_diff_seconds = timed(lambda: client.get(preview_url))
        upload_id = preview_url.split("upload_id=", 1)[1].split("&", 1)[0]
        confirm_response, confirm_seconds = timed(lambda: client.post(f"/source-datasets/{upload_id}/confirm", data={
            "csrf_token": client.environ_base["HTTP_X_CSRF_TOKEN"],
        }))
        if confirm_response.status_code != 302:
            raise RuntimeError(f"{count} row source confirmation failed with HTTP {confirm_response.status_code}")
        db = sqlite3.connect(db_path)
        try:
            dataset_id = db.execute("SELECT id FROM institution_source_datasets WHERE institution='MITAOE Demo Campus' AND name=?", (dataset_name,)).fetchone()
        finally:
            db.close()

        previous = [row["record"] for row in rows if not row["errors"]]
        changed = [dict(record) for record in previous]
        if changed:
            changed[-1]["course"] = "Changed benchmark course"
        _, diff_seconds = timed(lambda: version_diff(previous, changed))
        _, compare_seconds = timed(lambda: compare_student(previous[0], previous))

        student = previous[0]
        created = client.post("/api/v1/students", json={
            "student_code": student["institution_student_id"], "full_name": student["full_name"],
            "course": student["course"], "academic_year": student["semester"], "email": student["email"],
        })
        if created.status_code != 201:
            raise RuntimeError(f"{count} row synthetic comparison student creation failed")
        sid = created.json["id"]
        _, route_compare_seconds = timed(lambda: client.post(f"/students/{sid}/compare-source", data={
            "dataset_id": dataset_id[0], "csrf_token": client.environ_base["HTTP_X_CSRF_TOKEN"],
        }))
        print(f"{count} rows | parse+validation={validation_seconds:.4f}s | upload+stage={import_seconds:.4f}s "
              f"| preview diff/render={preview_diff_seconds:.4f}s | confirm/write={confirm_seconds:.4f}s "
              f"| version diff={diff_seconds:.4f}s | compare service={compare_seconds:.4f}s "
              f"| compare route+audit={route_compare_seconds:.4f}s")
    client = None
    with flask_app.app_context():
        from backend.db import close_db
        close_db()
    gc.collect()
    temp.cleanup()


if __name__ == "__main__":
    main()
