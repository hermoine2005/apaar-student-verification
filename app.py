import csv
import hashlib
import io
import json
import os
import hmac
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, Response, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from backend.audit import verify_chain
from backend.audit import record_event
from backend.cases import create_case
from backend.data_quality import validate_student_record
from backend.source_data import (parse_source_csv, compare_student, encode_preview,
                                 version_diff, MAX_SOURCE_BYTES,
                                 SOURCE_COMPARISON_RULESET_VERSION)
from backend.verification import provider_configuration

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

# ---------------------------------------------------------
# Application configuration
# ---------------------------------------------------------

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "APAAR_DB_PATH",
    os.path.join(APP_DIR, "instance", "apaar_demo.db")
)

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__)
configured_secret = os.environ.get("SECRET_KEY", "").strip()
if configured_secret in {"", "replace-with-a-long-random-secret", "development-only-change-me"}:
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Set a private SECRET_KEY before starting in production mode")
    configured_secret = os.urandom(32).hex()
app.secret_key = configured_secret
app.config["APAAR_DB_PATH"] = DB_PATH
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.config["CASE_AGE_THRESHOLDS_DAYS"] = (7, 30)
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW = 15 * 60
login_failures = {}


@app.before_request
def protect_cookie_authenticated_posts():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("_csrf_token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(400, description="The request security token is missing or invalid.")


def backup_before_schema_upgrade():
    """Create a consistent SQLite snapshot before additive startup migrations."""
    if not os.path.isfile(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return
    source = sqlite3.connect(DB_PATH)
    try:
        tables = {row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if not tables:
            return
        required_tables = {"users", "audit_logs", "workflow_cases", "duplicate_candidates", "audit_events", "import_jobs", "import_job_rows", "case_events", "case_evidence", "verification_runs", "verification_rule_results", "app_migrations", "institution_source_datasets", "institution_source_uploads", "institution_source_records", "institution_source_comparisons"}
        missing_tables = required_tables - tables
        needs_upgrade = bool(missing_tables)
        triggers = {row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        required_triggers = {
            "trg_case_events_scope_insert", "trg_case_evidence_scope_insert",
            "trg_workflow_case_student_insert", "trg_workflow_case_student_update",
        }
        needs_upgrade = needs_upgrade or bool(required_triggers - triggers)
        for table, column in (("users", "institution"), ("audit_logs", "institution")):
            if table in tables:
                columns = {row[1] for row in source.execute(f"PRAGMA table_info({table})")}
                needs_upgrade = needs_upgrade or column not in columns
        if "students" in tables:
            student_columns = {row[1] for row in source.execute("PRAGMA table_info(students)")}
            needs_upgrade = needs_upgrade or "archived_at" not in student_columns
        if "institution_source_uploads" in tables:
            source_columns = {row[1] for row in source.execute("PRAGMA table_info(institution_source_uploads)")}
            needs_upgrade = needs_upgrade or "change_summary_json" not in source_columns
        if "duplicate_candidates" in tables:
            candidate_columns = {row[1] for row in source.execute("PRAGMA table_info(duplicate_candidates)")}
            needs_upgrade = needs_upgrade or "decided_at" not in candidate_columns
        if "workflow_cases" in tables:
            case_columns = {row[1] for row in source.execute("PRAGMA table_info(workflow_cases)")}
            needs_upgrade = needs_upgrade or not {"legacy_source", "legacy_id", "legacy_status", "reviewer_id", "decision_at"}.issubset(case_columns)
        if "users" in tables:
            user_columns = {row[1] for row in source.execute("PRAGMA table_info(users)")}
            needs_upgrade = needs_upgrade or not {"is_active", "created_at", "updated_at"}.issubset(user_columns)
        if not needs_upgrade:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        database_name = os.path.splitext(os.path.basename(DB_PATH))[0]
        backup_path = os.path.join(os.path.dirname(DB_PATH), f"{database_name}.pre-upgrade-{stamp}.db")
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
        verification = sqlite3.connect(backup_path)
        try:
            if verification.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Pre-upgrade database backup failed its integrity check")
            original_tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            copied_tables = {row[0] for row in verification.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if original_tables != copied_tables:
                raise RuntimeError("Pre-upgrade database backup has a different table set")
            for table_name in original_tables:
                quoted = '"' + table_name.replace('"', '""') + '"'
                source_count = source.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
                backup_count = verification.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
                if source_count != backup_count:
                    raise RuntimeError(f"Pre-upgrade database backup row count differs for {table_name}")
        finally:
            verification.close()
    finally:
        source.close()


backup_before_schema_upgrade()

# Register the additional backend API.
# This does not replace any existing Flask pages or routes.
from backend import register_backend
register_backend(app)


# ---------------------------------------------------------
# Database and utility functions
# ---------------------------------------------------------

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def spreadsheet_safe(value):
    text = str(value or "")
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def connect_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    app.config["APAAR_DB_PATH"] = DB_PATH
    with connect_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            institution TEXT NOT NULL DEFAULT 'MITAOE Demo Campus',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_student_id TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            institution TEXT NOT NULL DEFAULT 'Demo Institution',
            course TEXT NOT NULL DEFAULT '',
            semester TEXT NOT NULL DEFAULT '',
            apaar_id TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending verification',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        );

        CREATE TABLE IF NOT EXISTS verification_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            findings TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'Local rule engine',
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id)
                REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution TEXT NOT NULL DEFAULT 'MITAOE Demo Campus',
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            entity TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS import_jobs (
            id TEXT PRIMARY KEY,
            institution TEXT NOT NULL,
            created_by TEXT NOT NULL,
            file_name TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'preview',
            accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            confirmed_at TEXT,
            UNIQUE(institution, content_hash)
        );

        CREATE TABLE IF NOT EXISTS import_job_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            student_code TEXT NOT NULL DEFAULT '',
            full_name TEXT NOT NULL DEFAULT '',
            course TEXT NOT NULL DEFAULT '',
            semester TEXT NOT NULL DEFAULT '',
            apaar_id TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            errors_json TEXT NOT NULL DEFAULT '[]',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            is_valid INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(job_id) REFERENCES import_jobs(id) ON DELETE CASCADE,
            UNIQUE(job_id, row_number)
        );

        CREATE TABLE IF NOT EXISTS institution_source_datasets (
            id TEXT PRIMARY KEY,
            institution TEXT NOT NULL,
            name TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(institution,name)
        );
        CREATE TABLE IF NOT EXISTS institution_source_uploads (
            id TEXT PRIMARY KEY,
            institution TEXT NOT NULL,
            dataset_id TEXT,
            dataset_name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 0,
            created_by TEXT NOT NULL,
            file_name TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'preview',
            preview_json TEXT NOT NULL,
            accepted_count INTEGER NOT NULL,
            rejected_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            confirmed_at TEXT,
            change_summary_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(institution,content_hash),
            FOREIGN KEY(dataset_id) REFERENCES institution_source_datasets(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS institution_source_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            upload_id TEXT NOT NULL,
            dataset_version INTEGER NOT NULL,
            row_number INTEGER NOT NULL,
            institution_student_id TEXT NOT NULL,
            full_name TEXT NOT NULL,
            course TEXT NOT NULL DEFAULT '',
            semester TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(dataset_id) REFERENCES institution_source_datasets(id) ON DELETE RESTRICT,
            FOREIGN KEY(upload_id) REFERENCES institution_source_uploads(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_source_records_lookup
            ON institution_source_records(institution,dataset_id,dataset_version,institution_student_id);
        CREATE TABLE IF NOT EXISTS institution_source_comparisons (
            id TEXT PRIMARY KEY,
            institution TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            dataset_version INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            actor TEXT NOT NULL,
            outcome TEXT NOT NULL,
            explanation TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            run_status TEXT NOT NULL DEFAULT 'completed',
            ruleset_version TEXT NOT NULL DEFAULT 'institution-source-comparison-v1',
            input_digest TEXT NOT NULL DEFAULT '',
            result_digest TEXT NOT NULL DEFAULT '',
            student_updated_at_snapshot TEXT NOT NULL DEFAULT '',
            outcome_counts_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE RESTRICT,
            FOREIGN KEY(dataset_id) REFERENCES institution_source_datasets(id) ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_students_name
            ON students(full_name);

        CREATE INDEX IF NOT EXISTS idx_students_status
            ON students(status);
        """)

        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        if "institution" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN institution TEXT NOT NULL DEFAULT 'MITAOE Demo Campus'")
        if "is_active" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "created_at" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        if "updated_at" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")
        db.execute("UPDATE users SET created_at=COALESCE(created_at,?), updated_at=COALESCE(updated_at,?)",
                   (now(), now()))
        audit_columns = {row[1] for row in db.execute("PRAGMA table_info(audit_logs)")}
        if "institution" not in audit_columns:
            db.execute("ALTER TABLE audit_logs ADD COLUMN institution TEXT NOT NULL DEFAULT 'MITAOE Demo Campus'")
        student_columns = {row[1] for row in db.execute("PRAGMA table_info(students)")}
        if "archived_at" not in student_columns:
            db.execute("ALTER TABLE students ADD COLUMN archived_at TEXT")
        source_upload_columns = {row[1] for row in db.execute("PRAGMA table_info(institution_source_uploads)")}
        if "change_summary_json" not in source_upload_columns:
            db.execute("ALTER TABLE institution_source_uploads ADD COLUMN change_summary_json TEXT NOT NULL DEFAULT '{}'")
        comparison_columns = {row[1] for row in db.execute("PRAGMA table_info(institution_source_comparisons)")}
        comparison_additions = {
            "run_status": "TEXT NOT NULL DEFAULT 'completed'",
            "ruleset_version": "TEXT NOT NULL DEFAULT 'institution-source-comparison-v1'",
            "input_digest": "TEXT NOT NULL DEFAULT ''",
            "result_digest": "TEXT NOT NULL DEFAULT ''",
            "student_updated_at_snapshot": "TEXT NOT NULL DEFAULT ''",
            "outcome_counts_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, declaration in comparison_additions.items():
            if column not in comparison_columns:
                db.execute(f"ALTER TABLE institution_source_comparisons ADD COLUMN {column} {declaration}")

        admin_exists = db.execute(
            "SELECT id FROM users WHERE username='admin'"
        ).fetchone()
        if not admin_exists:
            admin_password = os.environ.get("DEMO_ADMIN_PASSWORD", "")
            if os.environ.get("FLASK_ENV") == "production" and len(admin_password) < 16:
                raise RuntimeError("Set a private DEMO_ADMIN_PASSWORD of at least 16 characters before initializing the production admin")
            if not admin_password:
                admin_password = "ChangeMe123!"
            db.execute(
                "INSERT INTO users(username,password_hash,role,institution,is_active,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
                (
                    "admin",
                    generate_password_hash(admin_password),
                    "admin",
                    "MITAOE Demo Campus",
                    now(),
                    now(),
                ),
            )

        if db.execute(
            "SELECT COUNT(*) FROM students"
        ).fetchone()[0] == 0:
            sample = [
                (
                    "DEMO-1001", "Aarav Sharma", "MITAOE Demo Campus",
                    "Computer Engineering", "4", "DEMO-APAAR-0001",
                    "aarav@example.test", "Pending verification",
                    "Synthetic demo record",
                ),
                (
                    "DEMO-1002", "Ananya Patil", "MITAOE Demo Campus",
                    "Information Technology", "3", "DEMO-APAAR-0002",
                    "ananya@example.test", "Pending verification",
                    "Synthetic demo record",
                ),
                (
                    "DEMO-1003", "Rohan Kulkarni", "MITAOE Demo Campus",
                    "Computer Engineering", "4", "DEMO-APAAR-0003",
                    "rohan@example.test", "Needs review",
                    "Synthetic demo record",
                ),
                (
                    "DEMO-1004", "Ananya Patil", "MITAOE Demo Campus",
                    "Information Technology", "3", "DEMO-APAAR-0004",
                    "ananya2@example.test", "Pending verification",
                    "Synthetic duplicate candidate for demonstration",
                ),
            ]

            for row in sample:
                db.execute("""
                    INSERT INTO students(
                        institution_student_id, full_name, institution,
                        course, semester, apaar_id, email, status,
                        notes, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """, (*row, now(), now()))

            db.execute("""
                INSERT INTO audit_logs(
                    actor, action, entity, entity_id, details, created_at
                ) VALUES(?,?,?,?,?,?)
            """, (
                "system", "seed_demo_data", "students", "4",
                "Inserted synthetic sample records", now()
            ))

        legacy_counts = db.execute("""SELECT institution,COUNT(*) AS count FROM students
            WHERE lower(trim(status)) IN ('verified','pending','failed') GROUP BY institution""").fetchall()
        db.execute("UPDATE students SET status='Needs review' WHERE lower(trim(status))='verified'")
        db.execute("UPDATE students SET status='Pending verification' WHERE lower(trim(status))='pending'")
        db.execute("UPDATE students SET status='Failed to verify' WHERE lower(trim(status))='failed'")
        for legacy in legacy_counts:
            db.execute("""INSERT INTO audit_logs(institution,actor,action,entity,entity_id,details,created_at)
                VALUES(?, 'system','legacy_status_migration','students','status-labels',?,?)""",
                (legacy["institution"], f"Normalized {legacy['count']} legacy status labels; ambiguous Verified mapped to Needs review.", now()))

        db.commit()

    # The website verification table is created above. Run the idempotent
    # bridge after both schemas exist so website-only startup also completes it.
    from backend.db import init_db as init_backend_schema
    with app.app_context():
        init_backend_schema()
    # Status claims require a current structured result; preserve legacy rows as review work.
    with connect_db() as db:
        migration = "verification_status_provenance_v1"
        applied = db.execute("SELECT 1 FROM app_migrations WHERE name=?", (migration,)).fetchone()
        if not applied:
            candidates = db.execute("""SELECT s.id,s.institution,s.status,v.overall_json,v.provider_name,v.provider_outcome,v.status AS run_status
                FROM students s LEFT JOIN verification_runs v ON v.id=(SELECT id FROM verification_runs
                    WHERE student_id=s.id AND institution_id=s.institution ORDER BY created_at DESC,id DESC LIMIT 1)
                WHERE s.status IN ('Demo-validated','Verified against source')""").fetchall()
            invalid_by_institution = {}
            for row in candidates:
                valid = False
                if row["run_status"] == row["status"] and row["overall_json"]:
                    try:
                        provider = json.loads(row["overall_json"]).get("provider", {})
                        if row["status"] == "Demo-validated":
                            valid = row["provider_name"] == "synthetic_mock" and row["provider_outcome"] == "match" and provider.get("authoritative") is False
                        else:
                            valid = row["provider_name"] not in {"synthetic_mock", "disabled"} and row["provider_outcome"] == "match" and provider.get("authoritative") is True
                    except (TypeError, ValueError):
                        valid = False
                if not valid:
                    db.execute("UPDATE students SET status='Needs review' WHERE id=? AND institution=?", (row["id"], row["institution"]))
                    invalid_by_institution[row["institution"]] = invalid_by_institution.get(row["institution"], 0) + 1
            for institution, count in invalid_by_institution.items():
                db.execute("""INSERT INTO audit_logs(institution,actor,action,entity,entity_id,details,created_at)
                    VALUES(?, 'system','verification_provenance_migration','students','status-labels',?,?)""",
                    (institution, f"Moved {count} status label(s) without matching structured provider evidence to Needs review.", now()))
            db.execute("INSERT INTO app_migrations(name,applied_at) VALUES(?,?)", (migration, now()))
            db.commit()


def audit(action, entity, entity_id, details):
    with connect_db() as db:
        db.execute("""
            INSERT INTO audit_logs(
                institution, actor, action, entity, entity_id, details, created_at
            ) VALUES(?,?,?,?,?,?,?)
        """, (
            session.get("institution", "MITAOE Demo Campus"),
            session.get("username", "system"),
            action,
            entity,
            str(entity_id),
            details[:500],
            now(),
        ))
        db.commit()


# ---------------------------------------------------------
# Authentication
# ---------------------------------------------------------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login", next=request.path))
        with connect_db() as db:
            user = db.execute(
                "SELECT role, institution, is_active FROM users WHERE username=?",
                (session["username"],),
            ).fetchone()
        if not user or not user["is_active"]:
            session.clear()
            return redirect(url_for("login", next=request.path))
        session["role"] = user["role"]
        session["institution"] = user["institution"]
        return fn(*args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with connect_db() as db:
                user = db.execute(
                    "SELECT role,is_active FROM users WHERE username=?",
                    (session.get("username"),),
                ).fetchone()
            role = ({"admin": "institution_admin"}.get(user["role"], user["role"])
                    if user else "")
            if not user or not user["is_active"] or role not in allowed_roles:
                if request.path.startswith("/api/"):
                    return {"error": "forbidden", "message": "Role is not authorized"}, 403
                flash("Your account cannot perform that action.", "error")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorate


def write_role_required(*allowed_roles):
    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if request.method == "POST":
                with connect_db() as db:
                    user = db.execute(
                        "SELECT role,is_active FROM users WHERE username=?",
                        (session.get("username"),),
                    ).fetchone()
                role = ({"admin": "institution_admin"}.get(user["role"], user["role"])
                        if user else "")
                if not user or not user["is_active"] or role not in allowed_roles:
                    return {"error": "forbidden", "message": "Role is not authorized"}, 403
            return fn(*args, **kwargs)
        return wrapper
    return decorate


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        client_ip = request.remote_addr or "unknown"
        cutoff = time.time() - LOGIN_FAILURE_WINDOW
        recent_failures = [stamp for stamp in login_failures.get(client_ip, []) if stamp > cutoff]
        if len(recent_failures) >= LOGIN_FAILURE_LIMIT:
            login_failures[client_ip] = recent_failures
            flash("Too many sign-in attempts. Try again in 15 minutes.", "error")
            return render_template("login.html", show_demo_credentials=os.environ.get("FLASK_ENV") != "production"), 429

        with connect_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE username=? AND is_active=1",
                (username,)
            ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            login_failures.pop(client_ip, None)
            session.clear()
            session["_csrf_token"] = secrets.token_urlsafe(32)
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["institution"] = user["institution"]
            session["_fresh"] = True
            session.permanent = True
            audit("login", "user", user["username"], "Successful login")
            return redirect(url_for("dashboard"))

        recent_failures.append(time.time())
        login_failures[client_ip] = recent_failures
        flash("Invalid username or password.", "error")

    return render_template("login.html", show_demo_credentials=os.environ.get("FLASK_ENV") != "production")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    audit(
        "logout", "user", session.get("username", ""),
        "Session ended"
    )
    session.clear()
    return redirect(url_for("login"))


@app.get("/admin/users")
@login_required
@role_required("institution_admin")
def admin_users():
    with connect_db() as db:
        users = db.execute("""
            SELECT id,username,role,institution,is_active,created_at
            FROM users WHERE institution=? ORDER BY username
        """, (session.get("institution"),)).fetchall()
    return render_template("admin_users.html", users=users,
                           assignable_roles=("operator", "verifier", "auditor"))


@app.post("/admin/users")
@login_required
@role_required("institution_admin")
def admin_user_create():
    from backend.db import get_db
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "")
    if (not username or len(username) > 40
            or not all(ch.isalnum() or ch in "._-" for ch in username)
            or len(username) < 3):
        flash("Username must be 3–40 letters, numbers, dots, underscores, or hyphens.", "error")
        return redirect(url_for("admin_users"))
    if len(password) < 12 or len(password) > 256:
        flash("Set a password between 12 and 256 characters.", "error")
        return redirect(url_for("admin_users"))
    if role not in {"operator", "verifier", "auditor"}:
        flash("Select an approved non-administrator role.", "error")
        return redirect(url_for("admin_users"))
    db = get_db()
    timestamp = now()
    try:
        cursor = db.execute("""
            INSERT INTO users(username,password_hash,role,institution,is_active,created_at,updated_at)
            VALUES(?,?,?,?,1,?,?)
        """, (username, generate_password_hash(password), role,
              session.get("institution"), timestamp, timestamp))
        record_event(session.get("institution"), session.get("username"),
                     "account.created", "user", str(cursor.lastrowid),
                     {"username": username, "role": role})
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash("That username is already in use.", "error")
        return redirect(url_for("admin_users"))
    flash("User account created for this institution.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/role")
@login_required
@role_required("institution_admin")
def admin_user_role(user_id):
    from backend.db import get_db
    role = request.form.get("role", "")
    if role not in {"operator", "verifier", "auditor"}:
        flash("Only operator, verifier, and auditor roles can be assigned here.", "error")
        return redirect(url_for("admin_users"))
    db = get_db()
    user = db.execute("SELECT username,role FROM users WHERE id=? AND institution=?",
                      (user_id, session.get("institution"))).fetchone()
    if not user:
        abort(404)
    if user["username"] == session.get("username"):
        flash("You cannot change your own role.", "error")
        return redirect(url_for("admin_users"))
    old_role = user["role"]
    db.execute("UPDATE users SET role=?,updated_at=? WHERE id=? AND institution=?",
               (role, now(), user_id, session.get("institution")))
    record_event(session.get("institution"), session.get("username"),
                 "account.role_changed", "user", str(user_id),
                 {"from": old_role, "to": role})
    db.commit()
    flash("Account role updated.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/active")
@login_required
@role_required("institution_admin")
def admin_user_active(user_id):
    from backend.db import get_db
    db = get_db()
    user = db.execute("SELECT username,role,is_active FROM users WHERE id=? AND institution=?",
                      (user_id, session.get("institution"))).fetchone()
    if not user:
        abort(404)
    if user["username"] == session.get("username"):
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin_users"))
    active = 0 if user["is_active"] else 1
    db.execute("UPDATE users SET is_active=?,updated_at=? WHERE id=? AND institution=?",
               (active, now(), user_id, session.get("institution")))
    record_event(session.get("institution"), session.get("username"),
                 "account.activated" if active else "account.deactivated",
                 "user", str(user_id), {"username": user["username"]})
    db.commit()
    flash("Account " + ("activated." if active else "deactivated."), "success")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------
# Shared template context and security headers
# ---------------------------------------------------------

@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.context_processor
def inject_globals():
    return {
        "current_year": datetime.now().year,
        "csrf_token": lambda: session.get("_csrf_token", ""),
    }


# ---------------------------------------------------------
# Dashboard
# ---------------------------------------------------------

@app.route("/")
@login_required
@role_required("institution_admin", "operator", "verifier", "auditor")
def dashboard():
    with connect_db() as db:
        institution = session.get("institution")
        total = db.execute("SELECT COUNT(*) FROM students WHERE institution=? AND archived_at IS NULL", (institution,)).fetchone()[0]

        latest_results = db.execute("""SELECT s.status AS student_status,v.status AS run_status,v.provider_name,
            v.provider_outcome,v.overall_json FROM students s JOIN verification_runs v ON v.id=(
                SELECT id FROM verification_runs WHERE student_id=s.id AND institution_id=s.institution
                ORDER BY created_at DESC,id DESC LIMIT 1)
            WHERE s.institution=? AND s.archived_at IS NULL""", (institution,)).fetchall()
        verified = demo_validated = 0
        for result in latest_results:
            if result["student_status"] != result["run_status"] or result["provider_outcome"] != "match":
                continue
            try:
                provider = json.loads(result["overall_json"]).get("provider", {})
            except (TypeError, ValueError):
                continue
            if result["student_status"] == "Demo-validated" and result["provider_name"] == "synthetic_mock" and provider.get("authoritative") is False:
                demo_validated += 1
            elif result["student_status"] == "Verified against source" and result["provider_name"] not in {"synthetic_mock", "disabled"} and provider.get("authoritative") is True:
                verified += 1

        pending = db.execute(
            "SELECT COUNT(*) FROM students WHERE institution=? AND archived_at IS NULL AND status IN ('Pending','Pending verification','Draft','In progress')", (institution,)
        ).fetchone()[0]

        review = db.execute(
            "SELECT COUNT(*) FROM students WHERE institution=? AND archived_at IS NULL AND status IN ('Needs review','Discrepancy detected','Failed to verify','Expired or stale')", (institution,)
        ).fetchone()[0]
        cases_attention = db.execute("""SELECT COUNT(*) FROM workflow_cases
            WHERE institution_id=? AND status IN ('open','in_review','waiting_for_evidence','escalated')""",
            (institution,)).fetchone()[0]
        assignment_counts = db.execute("""SELECT
            SUM(CASE WHEN COALESCE(assigned_to,'')<>'' THEN 1 ELSE 0 END),
            SUM(CASE WHEN COALESCE(assigned_to,'')='' THEN 1 ELSE 0 END)
            FROM workflow_cases WHERE institution_id=?
              AND status IN ('open','in_review','waiting_for_evidence','escalated')""",
            (institution,)).fetchone()
        assigned_cases, unassigned_cases = (assignment_counts[0] or 0, assignment_counts[1] or 0)
        duplicate_reviews = db.execute("""SELECT COUNT(*) FROM duplicate_candidates
            WHERE institution_id=? AND status='pending_review'""", (institution,)).fetchone()[0]
        pending_imports = db.execute("SELECT COUNT(*) FROM import_jobs WHERE institution=? AND status='preview'", (institution,)).fetchone()[0]
        candidate_student_ids = {value for row in db.execute("""SELECT student_a_id,student_b_id
            FROM duplicate_candidates WHERE institution_id=? AND status='pending_review'""", (institution,))
            for value in row}
        quality_rows = db.execute("SELECT * FROM students WHERE institution=? AND archived_at IS NULL", (institution,)).fetchall()
        quality_issues = sum(bool(validate_student_record(
            dict(row), potential_duplicate=row["id"] in candidate_student_ids
        )) for row in quality_rows)
        status_distribution = db.execute("""SELECT status,COUNT(*) AS count FROM students
            WHERE institution=? AND archived_at IS NULL GROUP BY status ORDER BY count DESC,status""",
            (institution,)).fetchall()
        case_age_distribution = db.execute("""SELECT CASE
            WHEN julianday(created_at) IS NULL THEN 'Unknown age'
            WHEN julianday('now')-julianday(created_at)<7 THEN 'Under 7 days'
            WHEN julianday('now')-julianday(created_at)<30 THEN '7-29 days'
            ELSE '30+ days' END AS age_band,COUNT(*) AS count
            FROM workflow_cases WHERE institution_id=?
            AND status IN ('open','in_review','waiting_for_evidence','escalated')
            GROUP BY age_band ORDER BY CASE age_band WHEN 'Under 7 days' THEN 1 WHEN '7-29 days' THEN 2 ELSE 3 END""",
            (institution,)).fetchall()
        recent_import_rows = db.execute("""SELECT id,file_name,status,accepted_count,rejected_count,created_at
            FROM import_jobs WHERE institution=? ORDER BY created_at DESC LIMIT 5""", (institution,)).fetchall()
        recent_import_ids = [row["id"] for row in recent_import_rows]
        recent_warning_counts = {job_id: 0 for job_id in recent_import_ids}
        if recent_import_ids:
            placeholders = ",".join("?" for _ in recent_import_ids)
            counts = db.execute(f"""SELECT job_id,SUM(CASE WHEN trim(warnings_json) NOT IN ('','[]') THEN 1 ELSE 0 END) AS count
                FROM import_job_rows WHERE job_id IN ({placeholders}) GROUP BY job_id""", recent_import_ids).fetchall()
            recent_warning_counts.update({row["job_id"]: row["count"] or 0 for row in counts})
        recent_imports = [{**dict(row), "warning_rows": recent_warning_counts[row["id"]]} for row in recent_import_rows]

        recent = db.execute(
            "SELECT * FROM students WHERE institution=? AND archived_at IS NULL ORDER BY updated_at DESC LIMIT 6", (institution,)
        ).fetchall()

        logs = db.execute("""SELECT actor,action,entity,entity_id,details,created_at FROM (
            SELECT actor,action,entity,entity_id,details,created_at FROM audit_logs WHERE institution=?
            UNION ALL
            SELECT actor_id AS actor,action,entity_type AS entity,entity_id,
                COALESCE(reason,payload_json) AS details,created_at FROM audit_events WHERE institution_id=?
        ) ORDER BY created_at DESC LIMIT 6""", (institution, institution)).fetchall()

    return render_template(
        "dashboard.html",
        total=total,
        verified=verified,
        demo_validated=demo_validated,
        pending=pending,
        review=review,
        cases_attention=cases_attention,
        assigned_cases=assigned_cases,
        unassigned_cases=unassigned_cases,
        duplicate_reviews=duplicate_reviews,
        pending_imports=pending_imports,
        quality_issues=quality_issues,
        status_distribution=status_distribution,
        case_age_distribution=case_age_distribution,
        recent_imports=recent_imports,
        recent=recent,
        logs=logs,
    )


# ---------------------------------------------------------
# Student listing and search
# ---------------------------------------------------------

@app.route("/students")
@login_required
@role_required("institution_admin", "operator", "verifier", "auditor")
def students():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    course = request.args.get("course", "").strip()[:160]
    semester = request.args.get("semester", "").strip()[:40]
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per_page = 50
    where = " WHERE institution=? AND archived_at IS NULL"
    args = [session.get("institution")]

    if q:
        where += """
            AND (
                full_name LIKE ?
                OR institution_student_id LIKE ?
                OR institution LIKE ?
                OR course LIKE ?
            )
        """
        args += [f"%{q}%"] * 4

    if status in ("Draft", "Pending", "Pending verification", "In progress", "Verified against source", "Demo-validated", "Needs review", "Discrepancy detected", "Failed to verify", "Expired or stale", "Cancelled"):
        where += " AND status=?"
        args.append(status)
    else:
        status = ""
    if course:
        where += " AND course=?"
        args.append(course)
    if semester:
        where += " AND semester=?"
        args.append(semester)

    with connect_db() as db:
        institution = session.get("institution")
        total_count = db.execute("SELECT COUNT(*) FROM students" + where, args).fetchone()[0]
        pages = max(1, (total_count + per_page - 1) // per_page)
        page = min(page, pages)
        rows = db.execute("SELECT * FROM students" + where + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            [*args, per_page, (page - 1) * per_page]).fetchall()
        courses = [row[0] for row in db.execute("SELECT DISTINCT course FROM students WHERE institution=? AND archived_at IS NULL AND trim(course)<>'' ORDER BY course", (institution,))]
        semesters = [row[0] for row in db.execute("SELECT DISTINCT semester FROM students WHERE institution=? AND archived_at IS NULL AND trim(semester)<>'' ORDER BY semester", (institution,))]

    return render_template(
        "students.html",
        students=rows,
        q=q,
        status=status,
        course=course,
        semester=semester,
        courses=courses,
        semesters=semesters,
        page=page,
        pages=pages,
        total_count=total_count,
    )


# ---------------------------------------------------------
# Create and edit student
# ---------------------------------------------------------

@app.route("/students/new", methods=["GET", "POST"])
@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("institution_admin", "operator")
def student_form(student_id=None):
    with connect_db() as db:
        student = (
            db.execute(
                "SELECT * FROM students WHERE id=? AND institution=? AND archived_at IS NULL",
                (student_id, session.get("institution"))
            ).fetchone()
            if student_id else None
        )

    if student_id and not student:
        flash("Student record not found.", "error")
        return redirect(url_for("students"))

    if request.method == "POST":
        fields = (
            "institution_student_id", "full_name", "institution",
            "course", "semester", "apaar_id", "email", "notes"
        )
        values = {
            key: request.form.get(key, "").strip()
            for key in fields
        }
        if student_id and not values["apaar_id"]:
            values["apaar_id"] = student["apaar_id"] or ""
        # Institution membership is server supplied; a form field cannot move a record.
        values["institution"] = session.get("institution", "")

        if (
            not values["institution_student_id"]
            or not values["full_name"]
            or not values["institution"]
        ):
            flash(
                "Institutional student ID, full name, and institution are required.",
                "error",
            )
            return render_template(
                "student_form.html",
                student=student,
                values=values,
            )

        with connect_db() as db:
            duplicate_code = db.execute("SELECT 1 FROM students WHERE lower(institution_student_id)=lower(?) AND id<>COALESCE(?, -1)",
                (values["institution_student_id"], student_id)).fetchone() is not None
        field_issues = validate_student_record(values, duplicate_code=duplicate_code)
        field_errors = [issue for issue in field_issues if issue["severity"] == "error"]
        if field_errors:
            flash("Record not saved. " + " ".join(f"{issue['message']} {issue['next_action']}" for issue in field_errors), "error")
            return render_template("student_form.html", student=student, values=values)

        try:
            with connect_db() as db:
                if student_id:
                    db.execute("""
                        UPDATE students
                        SET institution_student_id=?, full_name=?,
                            institution=?, course=?, semester=?,
                            apaar_id=?, email=?, notes=?, updated_at=?
                        WHERE id=? AND institution=?
                    """, (
                        *[values[k] for k in fields],
                        now(),
                        student_id,
                        session.get("institution"),
                    ))
                else:
                    db.execute("""
                        INSERT INTO students(
                            institution_student_id, full_name, institution,
                            course, semester, apaar_id, email, notes,
                            status, created_at, updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        *[values[k] for k in fields],
                        "Pending verification", now(), now(),
                    ))
                    student_id = db.execute(
                        "SELECT last_insert_rowid()"
                    ).fetchone()[0]

                db.commit()

        except sqlite3.IntegrityError:
            flash("That institutional student ID already exists.", "error")
            return render_template(
                "student_form.html",
                student=student,
                values=values,
            )

        audit(
            "update" if student else "create",
            "student",
            student_id,
            "Student record saved; sensitive fields omitted",
        )
        flash("Student record saved.", "success")
        return redirect(
            url_for("student_detail", student_id=student_id)
        )

    return render_template(
        "student_form.html",
        student=student,
        values=({**dict(student), "apaar_id": ""} if student else {}),
    )


# ---------------------------------------------------------
# Student details and history
# ---------------------------------------------------------

@app.route("/students/<int:student_id>")
@login_required
@role_required("institution_admin", "operator", "verifier", "auditor")
def student_detail(student_id):
    from backend.db import get_db
    db = get_db()
    student = db.execute(
        "SELECT * FROM students WHERE id=? AND institution=? AND archived_at IS NULL",
        (student_id, session.get("institution"))
    ).fetchone()
    cases = db.execute("""
        SELECT * FROM workflow_cases
        WHERE student_id=? AND institution_id=? ORDER BY created_at DESC
    """, (student_id, session.get("institution"))).fetchall()
    last_run = db.execute("SELECT overall_json FROM verification_runs WHERE student_id=? AND institution_id=? ORDER BY created_at DESC LIMIT 1",
                          (student_id, session.get("institution"))).fetchone()
    verification_result = json.loads(last_run["overall_json"]) if last_run else None
    if verification_result:
        provider_result = verification_result.setdefault("provider", {})
        provider_result.setdefault("state", "SIMULATED" if provider_result.get("provider") in {"mock", "synthetic_mock"} else "NOT_CONFIGURED")

    if not student:
        flash("Student record not found.", "error")
        return redirect(url_for("students"))

    source_datasets = db.execute("""SELECT d.id,d.name,u.version,u.id AS upload_id
        FROM institution_source_datasets d JOIN institution_source_uploads u
          ON u.dataset_id=d.id AND u.institution=d.institution AND u.status='committed'
        WHERE d.institution=? AND u.version=(SELECT MAX(u2.version) FROM institution_source_uploads u2
          WHERE u2.dataset_id=d.id AND u2.institution=d.institution AND u2.status='committed')
        ORDER BY d.name""", (session.get("institution"),)).fetchall()
    source_comparisons = db.execute("""SELECT c.*,d.name AS dataset_name,s.updated_at AS current_student_updated_at,
        (SELECT MAX(u.version) FROM institution_source_uploads u
         WHERE u.dataset_id=c.dataset_id AND u.institution=c.institution AND u.status='committed') AS latest_dataset_version
        FROM institution_source_comparisons c
        JOIN institution_source_datasets d ON d.id=c.dataset_id AND d.institution=c.institution
        JOIN students s ON s.id=c.student_id AND s.institution=c.institution
        WHERE c.student_id=? AND c.institution=? ORDER BY c.created_at DESC LIMIT 10""",
        (student_id, session.get("institution"))).fetchall()

    possible_duplicate = db.execute("""SELECT 1 FROM duplicate_candidates
        WHERE institution_id=? AND status='pending_review'
        AND (student_a_id=? OR student_b_id=?) LIMIT 1""",
        (session.get("institution"), student_id, student_id)).fetchone() is not None
    quality_issues = validate_student_record(dict(student), potential_duplicate=possible_duplicate)
    duplicate_records = db.execute("""SELECT c.id,c.status,c.score,c.decision_by,c.decided_at,
        CASE WHEN c.student_a_id=? THEN b.id ELSE a.id END AS other_student_id,
        CASE WHEN c.student_a_id=? THEN b.institution_student_id ELSE a.institution_student_id END AS other_student_code
        FROM duplicate_candidates c
        JOIN students a ON a.id=c.student_a_id AND a.institution=c.institution_id
        JOIN students b ON b.id=c.student_b_id AND b.institution=c.institution_id
        WHERE c.institution_id=? AND (c.student_a_id=? OR c.student_b_id=?)
        ORDER BY CASE WHEN c.status='pending_review' THEN 0 ELSE 1 END,c.created_at DESC LIMIT 20""",
        (student_id, student_id, session.get("institution"), student_id, student_id)).fetchall()

    return render_template(
        "student_detail.html",
        student=student,
        cases=cases,
        verification_result=verification_result,
        quality_issues=quality_issues,
        duplicate_records=duplicate_records,
        can_edit=session.get("role") in {"admin", "institution_admin", "operator"},
        can_validate=session.get("role") in {"admin", "institution_admin", "operator", "verifier"},
        can_open_case=session.get("role") in {"admin", "institution_admin", "operator", "verifier"},
        source_datasets=source_datasets,
        source_comparisons=[{
            **dict(row), "fields": json.loads(row["fields_json"]),
            "is_stale": (row["dataset_version"] != row["latest_dataset_version"]
                         or row["student_updated_at_snapshot"] != row["current_student_updated_at"]
                         or row["ruleset_version"] != SOURCE_COMPARISON_RULESET_VERSION),
        } for row in source_comparisons],
        can_compare_source=session.get("role") in {"admin", "institution_admin", "operator", "verifier"},
        provider_configuration=provider_configuration(),
    )


# ---------------------------------------------------------
# Institution-provided source datasets (separate from student records)
# ---------------------------------------------------------

@app.route("/source-datasets", methods=["GET", "POST"])
@login_required
@role_required("institution_admin", "operator")
@write_role_required("institution_admin", "operator")
def source_datasets():
    institution = session.get("institution", "")
    report = None
    with connect_db() as db:
        history_rows = db.execute("""SELECT u.*,d.name FROM institution_source_uploads u
            LEFT JOIN institution_source_datasets d ON d.id=u.dataset_id AND d.institution=u.institution
            WHERE u.institution=? ORDER BY u.created_at DESC LIMIT 30""", (institution,)).fetchall()
        history = [{**dict(row), "changes": json.loads(row["change_summary_json"] or "{}")} for row in history_rows]
    preview_id = request.args.get("upload_id", "")
    if preview_id:
        with connect_db() as db:
            upload = db.execute("SELECT * FROM institution_source_uploads WHERE id=? AND institution=?",
                                (preview_id, institution)).fetchone()
            previous_rows = []
            if upload and upload["status"] == "preview":
                dataset = db.execute("SELECT id FROM institution_source_datasets WHERE institution=? AND name=?",
                                     (institution, upload["dataset_name"])).fetchone()
                if dataset:
                    previous_version = db.execute("SELECT MAX(version) FROM institution_source_uploads WHERE dataset_id=? AND status='committed'",
                                                  (dataset["id"],)).fetchone()[0]
                    if previous_version:
                        previous_rows = [dict(row) for row in db.execute("""SELECT institution_student_id,full_name,course,semester,email
                            FROM institution_source_records WHERE institution=? AND dataset_id=? AND dataset_version=?""",
                            (institution,dataset["id"],previous_version)).fetchall()]
        if upload:
            rows = json.loads(upload["preview_json"])
            current_rows = [row["record"] for row in rows if not row["errors"]]
            changes = json.loads(upload["change_summary_json"] or "{}") if upload["status"] == "committed" else version_diff(previous_rows, current_rows)
            report = {"job": upload, "rows": rows, "change_summary": changes}

    if request.method == "POST":
        name = request.form.get("dataset_name", "").strip()
        upload = request.files.get("file")
        if not name or len(name) > 120:
            flash("Provide a dataset name of 1 to 120 characters.", "error")
            return redirect(url_for("source_datasets"))
        if not upload or not upload.filename or not upload.filename.lower().endswith(".csv"):
            audit("source_dataset.import_rejected", "institution_source_dataset", "upload",
                  "Unsupported source file type; no file content stored")
            flash("Choose a CSV file. SQLite files and server paths are not accepted.", "error")
            return redirect(url_for("source_datasets"))
        raw = upload.stream.read(MAX_SOURCE_BYTES + 1)
        parsed, file_errors = parse_source_csv(raw)
        if file_errors:
            audit("source_dataset.import_rejected", "institution_source_dataset", "upload",
                  "Upload validation rejected; personal row data omitted")
            flash(file_errors[0], "error")
            return redirect(url_for("source_datasets"))
        digest = hashlib.sha256(raw).hexdigest()
        accepted = sum(not row["errors"] for row in parsed)
        rejected = len(parsed) - accepted
        upload_id = secrets.token_hex(16)
        stamp = now()
        try:
            with connect_db() as db:
                prior = db.execute("SELECT id FROM institution_source_uploads WHERE institution=? AND content_hash=?",
                                   (institution, digest)).fetchone()
                if prior:
                    flash("This exact source file was already previewed or imported. Its existing record is shown.", "success")
                    return redirect(url_for("source_datasets", upload_id=prior["id"]))
                db.execute("""INSERT INTO institution_source_uploads
                    (id,institution,dataset_name,created_by,file_name,content_hash,status,preview_json,accepted_count,rejected_count,created_at)
                    VALUES(?,?,?,?,?,?,'preview',?,?,?,?)""",
                    (upload_id,institution,name,session.get("username",""),upload.filename.replace("\\", "/").rsplit("/", 1)[-1][:255],digest,
                     encode_preview(parsed),accepted,rejected,stamp))
        except sqlite3.IntegrityError:
            flash("This source file has already been submitted for this institution.", "error")
            return redirect(url_for("source_datasets"))
        flash("Source dataset preview ready. No reference records were saved.", "success")
        return redirect(url_for("source_datasets", upload_id=upload_id))

    return render_template("source_datasets.html", history=history, report=report)


@app.post("/source-datasets/<upload_id>/confirm")
@login_required
@role_required("institution_admin", "operator")
def confirm_source_dataset(upload_id):
    institution, stamp = session.get("institution", ""), now()
    db = connect_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        upload = db.execute("SELECT * FROM institution_source_uploads WHERE id=? AND institution=?",
                            (upload_id, institution)).fetchone()
        if not upload:
            db.rollback()
            flash("Source preview not found.", "error")
            return redirect(url_for("source_datasets"))
        if upload["status"] == "committed":
            db.rollback()
            flash("This source dataset version was already saved.", "success")
            return redirect(url_for("source_datasets", upload_id=upload_id))
        rows = json.loads(upload["preview_json"])
        accepted = [row for row in rows if not row["errors"]]
        if not accepted:
            db.rollback()
            audit("source_dataset.import_rejected", "institution_source_dataset", upload_id,
                  "Source preview had no valid rows; no dataset was committed")
            flash("This preview contains no valid source rows and cannot be confirmed.", "error")
            return redirect(url_for("source_datasets", upload_id=upload_id))
        dataset = db.execute("SELECT id FROM institution_source_datasets WHERE institution=? AND name=?",
                             (institution, upload["dataset_name"])).fetchone()
        if dataset:
            dataset_id = dataset["id"]
        else:
            dataset_id = secrets.token_hex(16)
            db.execute("INSERT INTO institution_source_datasets(id,institution,name,created_by,created_at) VALUES(?,?,?,?,?)",
                       (dataset_id,institution,upload["dataset_name"],session.get("username",""),stamp))
        version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM institution_source_uploads WHERE dataset_id=? AND status='committed'",
                             (dataset_id,)).fetchone()[0]
        previous_version = version - 1
        previous_rows = []
        if previous_version:
            previous_rows = [dict(row) for row in db.execute("""SELECT institution_student_id,full_name,course,semester,email
                FROM institution_source_records WHERE institution=? AND dataset_id=? AND dataset_version=?""",
                (institution,dataset_id,previous_version)).fetchall()]
        accepted_records = [row["record"] for row in accepted]
        changes = version_diff(previous_rows, accepted_records)
        db.execute("UPDATE institution_source_uploads SET dataset_id=?,version=?,status='committed',confirmed_at=? WHERE id=? AND institution=? AND status='preview'",
                   (dataset_id,version,stamp,upload_id,institution))
        db.execute("UPDATE institution_source_uploads SET change_summary_json=? WHERE id=? AND institution=?",
                   (json.dumps(changes,sort_keys=True),upload_id,institution))
        db.executemany("""INSERT INTO institution_source_records
            (institution,dataset_id,upload_id,dataset_version,row_number,institution_student_id,full_name,course,semester,email)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [(institution,dataset_id,upload_id,version,row["line"],row["record"]["institution_student_id"],
              row["record"]["full_name"],row["record"].get("course",""),row["record"].get("semester",""),
              row["record"].get("email","")) for row in accepted])
        db.execute("INSERT INTO audit_logs(institution,actor,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?,?)",
                   (institution,session.get("username",""),"source_dataset_imported","institution_source_dataset",dataset_id,
                    f"Imported source dataset version {version}; {len(accepted)} records; sensitive values omitted.",stamp))
        db.commit()
    except sqlite3.Error:
        db.rollback()
        audit("source_dataset.import_failed", "institution_source_dataset", upload_id,
              "Source confirmation failed; no partial dataset records were committed")
        flash("Source dataset could not be saved. No partial records were committed.", "error")
        return redirect(url_for("source_datasets", upload_id=upload_id))
    finally:
        db.close()
    from backend.db import get_db
    workflow_db = get_db()
    record_event(institution, session.get("username"), "source_dataset.imported", "institution_source_dataset",
                 dataset_id, {"version": version, "record_count": len(accepted)})
    workflow_db.commit()
    flash(f"Institution-provided source dataset saved as version {version} ({len(accepted)} records).", "success")
    return redirect(url_for("source_datasets", upload_id=upload_id))


@app.post("/students/<int:student_id>/compare-source")
@login_required
@role_required("institution_admin", "operator", "verifier")
def compare_institution_source(student_id):
    from backend.db import get_db
    from backend.cases import create_case
    from backend.audit import record_event
    institution = session.get("institution", "")
    dataset_id = request.form.get("dataset_id", "")
    with connect_db() as db:
        student = db.execute("SELECT * FROM students WHERE id=? AND institution=? AND archived_at IS NULL",
                             (student_id,institution)).fetchone()
        source = db.execute("""SELECT d.id AS dataset_id,d.name,u.version,u.content_hash FROM institution_source_datasets d
            JOIN institution_source_uploads u ON u.dataset_id=d.id AND u.institution=d.institution AND u.status='committed'
            WHERE d.id=? AND d.institution=? AND u.version=(SELECT MAX(u2.version) FROM institution_source_uploads u2
              WHERE u2.dataset_id=d.id AND u2.institution=d.institution AND u2.status='committed')""",
            (dataset_id,institution)).fetchone()
        if not student or not source:
            flash("Student or institution source dataset was not found.", "error")
            return redirect(url_for("students"))
        source_rows = [dict(row) for row in db.execute("""SELECT institution_student_id,full_name,course,semester,email
            FROM institution_source_records WHERE institution=? AND dataset_id=? AND dataset_version=?""",
            (institution,dataset_id,source["version"])).fetchall()]
        duplicate_candidate = db.execute("""SELECT 1 FROM duplicate_candidates WHERE institution_id=?
            AND status='pending_review' AND (student_a_id=? OR student_b_id=?) LIMIT 1""",
            (institution,student_id,student_id)).fetchone() is not None
        result = compare_student(dict(student), source_rows, duplicate_candidate=duplicate_candidate)
        comparison_id = secrets.token_hex(16)
        stamp = now()
        fields_json = json.dumps(result["fields"], sort_keys=True, separators=(",", ":"))
        outcome_counts_json = json.dumps({result["outcome"]: 1}, sort_keys=True, separators=(",", ":"))
        provenance = {
            "dataset_id": source["dataset_id"], "dataset_version": source["version"],
            "input_digest": source["content_hash"], "ruleset_version": SOURCE_COMPARISON_RULESET_VERSION,
            "outcome": result["outcome"], "fields": result["fields"],
            "explanation": result["explanation"],
        }
        result_digest = hashlib.sha256(json.dumps(
            provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        db.execute("""INSERT INTO institution_source_comparisons
            (id,institution,dataset_id,dataset_version,student_id,actor,outcome,explanation,fields_json,
             run_status,ruleset_version,input_digest,result_digest,student_updated_at_snapshot,outcome_counts_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,'completed',?,?,?,?,?,?)""",
            (comparison_id,institution,dataset_id,source["version"],student_id,session.get("username",""),
             result["outcome"],result["explanation"],fields_json,SOURCE_COMPARISON_RULESET_VERSION,
             source["content_hash"],result_digest,student["updated_at"],outcome_counts_json,stamp))
        db.execute("INSERT INTO audit_logs(institution,actor,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?,?)",
                   (institution,session.get("username",""),"source_comparison","student",str(student_id),
                    f"Compared with institution dataset version {source['version']}; outcome {result['outcome']}; field values omitted.",stamp))
        db.commit()
    workflow_db = get_db()
    record_event(institution, session.get("username"), "source_comparison.completed", "source_comparison",
                 comparison_id, {"dataset_id": source["dataset_id"], "dataset_version": source["version"],
                                 "input_digest": source["content_hash"],
                                 "ruleset_version": SOURCE_COMPARISON_RULESET_VERSION,
                                 "run_status": "completed", "result_digest": result_digest,
                                 "outcome": result["outcome"], "fields": result["fields"]})
    if result["manual_review_required"]:
        try:
            create_case(workflow_db, institution_id=institution, student_id=str(student_id),
                case_type="institution_source_comparison", reason=f"Institution source comparison requires review: {result['outcome']}.",
                actor_id=session.get("username"), priority="high" if result["outcome"] == "MISMATCH" else "normal",
                summary=f"Institution-provided dataset comparison: {result['outcome']}",
                findings=result["explanation"], source=f"institution source dataset version {source['version']}; comparison {comparison_id}")
        except (LookupError, ValueError):
            workflow_db.rollback()
            flash("Comparison was saved, but the review case could not be created.", "error")
            return redirect(url_for("student_detail", student_id=student_id))
    workflow_db.commit()
    flash(f"Comparison against institution-provided data: {result['outcome']}. No student record was changed.",
          "success" if result["outcome"] == "MATCH" else "warning")
    return redirect(url_for("student_detail", student_id=student_id))


# ---------------------------------------------------------
# Delete student
# ---------------------------------------------------------

@app.route("/students/<int:student_id>/archive", methods=["POST"])
@login_required
@role_required("institution_admin")
def student_archive(student_id):
    with connect_db() as db:
        row = db.execute(
            "SELECT institution_student_id FROM students WHERE id=? AND institution=? AND archived_at IS NULL",
            (student_id, session.get("institution"))
        ).fetchone()

        if not row:
            flash("Student record not found.", "error")
        else:
            db.execute(
                "UPDATE students SET archived_at=?, updated_at=? WHERE id=? AND institution=? AND archived_at IS NULL",
                (now(), now(), student_id, session.get("institution"))
            )
            db.commit()

            audit(
                "archive", "student", student_id,
                "Archived student record; institutional identifier omitted",
            )
            from backend.db import get_db
            workflow_db = get_db()
            record_event(session.get("institution"), session.get("username"),
                         "student.archived", "student", str(student_id), {})
            workflow_db.commit()
            flash("Student record archived.", "success")

    return redirect(url_for("students"))


@app.get("/students/archived")
@login_required
@role_required("institution_admin")
def archived_students():
    with connect_db() as db:
        rows = db.execute("""
            SELECT * FROM students WHERE institution=? AND archived_at IS NOT NULL
            ORDER BY archived_at DESC LIMIT 200
        """, (session.get("institution"),)).fetchall()
    return render_template("archived_students.html", students=rows)


@app.post("/students/<int:student_id>/restore")
@login_required
@role_required("institution_admin")
def student_restore(student_id):
    institution = session.get("institution")
    replacement_code = request.form.get("institution_student_id", "").strip()
    db = connect_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""
            SELECT institution_student_id FROM students
            WHERE id=? AND institution=? AND archived_at IS NOT NULL
        """, (student_id, institution)).fetchone()
        if not row:
            db.rollback()
            flash("Archived student record was not found.", "error")
            return redirect(url_for("archived_students"))
        code = replacement_code or row["institution_student_id"]
        if not code or len(code) > 80:
            db.rollback()
            flash("Provide an institutional student ID up to 80 characters.", "error")
            return redirect(url_for("archived_students"))
        conflict = db.execute(
            "SELECT id FROM students WHERE institution_student_id=? AND id<>?",
            (code, student_id),
        ).fetchone()
        if conflict:
            db.rollback()
            flash("That student ID belongs to another record. Enter a new ID to resolve the conflict before restoring.", "error")
            return redirect(url_for("archived_students"))
        db.execute("""
            UPDATE students SET institution_student_id=?,archived_at=NULL,updated_at=?
            WHERE id=? AND institution=? AND archived_at IS NOT NULL
        """, (code, now(), student_id, institution))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash("The record could not be restored because its student ID conflicts with another record.", "error")
        return redirect(url_for("archived_students"))
    finally:
        db.close()
    audit("restore", "student", student_id, "Restored archived student record")
    from backend.db import get_db
    workflow_db = get_db()
    record_event(institution, session.get("username"), "student.restored",
                 "student", str(student_id), {})
    workflow_db.commit()
    flash("Student record restored with its original internal ID and history.", "success")
    return redirect(url_for("student_detail", student_id=student_id))


# ---------------------------------------------------------
# Local demo verification
# ---------------------------------------------------------

@app.route("/students/<int:student_id>/verify", methods=["POST"])
@login_required
@role_required("institution_admin", "operator", "verifier")
def verify_student(student_id):
    from backend.db import get_db
    db = get_db()
    student = db.execute(
        "SELECT * FROM students WHERE id=? AND institution=? AND archived_at IS NULL",
        (student_id, session.get("institution"))
    ).fetchone()

    if not student:
        flash("Student record not found.", "error")
        return redirect(url_for("students"))

    from backend.verification import persist_result
    scenario = request.form.get("mock_scenario", "")
    try:
        run_id, result = persist_result(db, student, session.get("institution"), session.get("username"), scenario or None)
    except ValueError as exc:
        db.rollback()
        flash(str(exc), "error")
        return redirect(url_for("student_detail", student_id=student_id))
    summary = f"{result['status']}: {result['explanation']}"
    findings_text = "\n".join(rule["explanation"] for rule in result["rules"] if rule["outcome"] != "pass") or "Local checks completed; provider result is synthetic and non-authoritative."
    create_case(
        db, institution_id=session.get("institution"), student_id=student_id,
        case_type="verification_run", reason=summary,
        actor_id=session.get("username"),
        initial_status="open" if result["manual_review_required"] else "recorded", summary=summary,
        findings=findings_text, source=f"ruleset local-rules-1.0; run {run_id}; synthetic provider only",
    )
    record_event(session.get("institution"), session.get("username"), "verification.completed",
        "verification_run", run_id, {"ruleset_version": "local-rules-1.0", "status": result["status"],
        "provider": result["provider"]["provider"], "provider_outcome": result["provider"]["outcome"],
        "provider_state": result["provider"]["state"],
        "manual_review_required": result["manual_review_required"]})
    db.commit()

    audit(
        "verify", "student", student_id,
        f"Verification run {run_id}; synthetic provider outcome {result['provider']['outcome']}; identifier omitted",
    )
    flash(
        "Local checks completed. No official APAAR lookup was performed.",
        "success",
    )
    return redirect(
        url_for("student_detail", student_id=student_id)
    )


# ---------------------------------------------------------
# CSV import
# ---------------------------------------------------------

@app.route("/imports", methods=["GET", "POST"])
@login_required
@role_required("institution_admin", "operator", "auditor")
@write_role_required("institution_admin", "operator")
def imports():
    institution = session.get("institution", "")
    report = None
    with connect_db() as db:
        history_rows = db.execute("SELECT * FROM import_jobs WHERE institution=? ORDER BY created_at DESC LIMIT 20", (institution,)).fetchall()
        history_ids = [row["id"] for row in history_rows]
        warning_counts = {job_id: 0 for job_id in history_ids}
        if history_ids:
            placeholders = ",".join("?" for _ in history_ids)
            warning_rows = db.execute(f"""SELECT job_id,SUM(CASE WHEN trim(warnings_json) NOT IN ('','[]') THEN 1 ELSE 0 END) AS count
                FROM import_job_rows WHERE job_id IN ({placeholders}) GROUP BY job_id""", history_ids).fetchall()
            warning_counts.update({row["job_id"]: row["count"] or 0 for row in warning_rows})
        history = [{**dict(row), "warning_rows": warning_counts[row["id"]]} for row in history_rows]
    selected_id = request.args.get("job_id", "")
    if selected_id:
        with connect_db() as db:
            job = db.execute("SELECT * FROM import_jobs WHERE id=? AND institution=?", (selected_id, institution)).fetchone()
            rows = db.execute("SELECT * FROM import_job_rows WHERE job_id=? ORDER BY row_number", (selected_id,)).fetchall() if job else []
        if job:
            report_rows = []
            for row in rows:
                item = dict(row)
                item["errors"] = json.loads(item.pop("errors_json"))
                item["warnings"] = json.loads(item.pop("warnings_json"))
                report_rows.append(item)
            report = {"job": job, "rows": report_rows,
                      "warning_rows": sum(bool(item["warnings"]) for item in report_rows),
                      "total_rows": len(report_rows)}

    if request.method == "POST":
        upload = request.files.get("file")
        if not upload or not upload.filename or not upload.filename.lower().endswith(".csv"):
            flash("Choose a CSV file.", "error")
            return redirect(url_for("imports"))
        raw = upload.stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            flash("Upload exceeds the 2 MB demo limit.", "error")
            return redirect(url_for("imports"))
        digest = hashlib.sha256(raw).hexdigest()
        with connect_db() as db:
            old_job = db.execute("SELECT id FROM import_jobs WHERE institution=? AND content_hash=?", (institution, digest)).fetchone()
        if old_job:
            flash("This file was already reviewed. Its existing preview or import result is shown.", "success")
            return redirect(url_for("imports", job_id=old_job["id"]))
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        except UnicodeDecodeError:
            flash("CSV must use UTF-8 encoding.", "error")
            return redirect(url_for("imports"))
        headers_found = {str(h or "").strip() for h in (reader.fieldnames or [])}
        if not {"institution_student_id", "full_name"}.issubset(headers_found):
            flash("CSV must include institution_student_id and full_name columns.", "error")
            return redirect(url_for("imports"))
        job_id, created_at, parsed, seen = secrets.token_hex(16), now(), [], set()
        accepted = rejected = 0
        with connect_db() as db:
            existing_codes = {str(r[0]).casefold().strip() for r in db.execute("SELECT institution_student_id FROM students")}
            names = {" ".join((r[0] or "").casefold().split()) for r in db.execute("SELECT full_name FROM students WHERE institution=? AND archived_at IS NULL", (institution,))}
            emails = {str(r[0]).casefold().strip() for r in db.execute("SELECT email FROM students WHERE institution=? AND archived_at IS NULL AND email<>''", (institution,))}
            for line_number, raw_row in enumerate(reader, start=2):
                row = {str(k or "").strip(): str(v or "").strip() for k, v in raw_row.items() if k is not None}
                code, name = row.get("institution_student_id", ""), row.get("full_name", "")
                course, semester = row.get("course", ""), row.get("semester", "")
                apaar_id, email, notes = row.get("apaar_id", ""), row.get("email", ""), row.get("notes", "")
                folded_code = code.casefold()
                duplicate_code = bool(folded_code and (folded_code in existing_codes or folded_code in seen))
                if folded_code: seen.add(folded_code)
                normalized_name = " ".join(name.casefold().split())
                duplicate_name = bool(normalized_name and normalized_name in names)
                duplicate_email = bool(email and email.casefold() in emails)
                quality_issues = validate_student_record(
                    {"institution_student_id": code, "full_name": name, "email": email,
                     "course": course, "semester": semester, "apaar_id": apaar_id, "notes": notes},
                    duplicate_code=duplicate_code, duplicate_name=duplicate_name,
                    duplicate_email=duplicate_email,
                )
                errors = [f"[{item['code']}] {item['message']} Next step: {item['next_action']}"
                          for item in quality_issues if item["severity"] == "error"]
                warnings = [f"[{item['code']}] {item['message']} Next step: {item['next_action']}"
                            for item in quality_issues if item["severity"] == "warning"]
                valid = int(not errors)
                accepted += valid
                rejected += 1 - valid
                parsed.append((job_id,line_number,code,name,course,semester,apaar_id,email,notes,json.dumps(errors),json.dumps(warnings),valid))
            db.execute("INSERT INTO import_jobs(id,institution,created_by,file_name,content_hash,status,accepted_count,rejected_count,created_at) VALUES(?,?,?,?,?,'preview',?,?,?)",
                (job_id,institution,session.get("username",""),os.path.basename(upload.filename)[:255],digest,accepted,rejected,created_at))
            db.executemany("""INSERT INTO import_job_rows(job_id,row_number,student_code,full_name,course,semester,apaar_id,email,notes,errors_json,warnings_json,is_valid)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", parsed)
            db.commit()
        flash("Preview ready. No student records were written.", "success")
        return redirect(url_for("imports", job_id=job_id))
    return render_template("imports.html", report=report, history=history)


@app.route("/imports/<job_id>/confirm", methods=["POST"])
@login_required
@role_required("institution_admin", "operator")
def confirm_import(job_id):
    institution, stamp = session.get("institution", ""), now()
    db = connect_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute("SELECT * FROM import_jobs WHERE id=? AND institution=?", (job_id,institution)).fetchone()
        if not job:
            db.rollback()
            flash("Import preview not found.", "error")
            return redirect(url_for("imports"))
        if job["status"] == "committed":
            db.rollback()
            flash("This import was already committed; no records were added again.", "success")
            return redirect(url_for("imports", job_id=job_id))
        rows = db.execute("SELECT * FROM import_job_rows WHERE job_id=? AND is_valid=1 ORDER BY row_number", (job_id,)).fetchall()
        existing = {str(r[0]).casefold().strip() for r in db.execute("SELECT institution_student_id FROM students")}
        if any(r["student_code"].casefold().strip() in existing for r in rows):
            db.rollback()
            flash("A record changed after preview. Upload a corrected file to create a fresh preview.", "error")
            return redirect(url_for("imports", job_id=job_id))
        for row in rows:
            db.execute("""INSERT INTO students(institution_student_id,full_name,institution,course,semester,apaar_id,email,notes,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (row["student_code"],row["full_name"],institution,row["course"],row["semester"],row["apaar_id"],row["email"],row["notes"],"Pending verification",stamp,stamp))
        db.execute("UPDATE import_jobs SET status='committed',confirmed_at=? WHERE id=? AND institution=?", (stamp,job_id,institution))
        db.execute("INSERT INTO audit_logs(institution,actor,action,entity,entity_id,details,created_at) VALUES(?,?,?,?,?,?,?)",
            (institution,session.get("username",""),"csv_import","students",job_id,f"Committed {len(rows)} rows from {job['file_name']}; sensitive fields omitted",stamp))
        db.commit()
        flash(f"Import confirmed: {len(rows)} valid student record(s) saved. Review data-quality findings in the student directory.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Import conflicts with existing data. No records were added.", "error")
    finally:
        db.close()
    return redirect(url_for("imports", job_id=job_id))


@app.route("/imports/<job_id>/errors.csv")
@login_required
@role_required("institution_admin", "operator")
def import_errors(job_id):
    institution = session.get("institution", "")
    with connect_db() as db:
        job = db.execute("SELECT id FROM import_jobs WHERE id=? AND institution=?", (job_id,institution)).fetchone()
        if not job:
            return {"error": "not_found"}, 404
        rows = db.execute("SELECT row_number,student_code,errors_json,warnings_json FROM import_job_rows WHERE job_id=? AND is_valid=0 ORDER BY row_number", (job_id,)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["row_number","institution_student_id","errors","warnings"])
    writer.writerows([(r["row_number"],spreadsheet_safe(r["student_code"]),"; ".join(json.loads(r["errors_json"])),"; ".join(json.loads(r["warnings_json"]))) for r in rows])
    return Response(output.getvalue(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=import-errors.csv"})


# CSV export
# ---------------------------------------------------------

@app.route("/students/export.csv")
@login_required
@role_required("institution_admin", "operator", "verifier", "auditor")
def export_students():
    with connect_db() as db:
        rows = db.execute("""
            SELECT institution_student_id, full_name, institution,
                   course, semester, status, email, updated_at
            FROM students WHERE institution=? AND archived_at IS NULL ORDER BY id
        """, (session.get("institution"),)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "institution_student_id", "full_name", "institution",
        "course", "semester", "status", "email", "updated_at",
    ])
    writer.writerows([tuple(spreadsheet_safe(value) for value in row) for row in rows])

    audit(
        "export", "students", "csv",
        f"Exported {len(rows)} rows; APAAR identifiers excluded",
    )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=student_records.csv"
        },
    )


# ---------------------------------------------------------
# Audit page
# ---------------------------------------------------------

@app.route("/audit")
@login_required
@role_required("institution_admin", "auditor")
def audit_page():
    action = request.args.get("action", "").strip()[:100]
    actor = request.args.get("actor", "").strip()[:120]
    action_like = f"%{action}%"
    actor_like = f"%{actor}%"
    with connect_db() as db:
        logs = db.execute("""
            SELECT * FROM audit_logs WHERE institution=? AND (?='' OR action LIKE ?)
                AND (?='' OR actor LIKE ?) ORDER BY id DESC LIMIT 300
        """, (session.get("institution"), action, action_like, actor, actor_like)).fetchall()
        workflow_events = db.execute("""
            SELECT actor_id, action, entity_type, entity_id, reason, created_at
            FROM audit_events WHERE institution_id=? AND (?='' OR action LIKE ?)
                AND (?='' OR actor_id LIKE ?) ORDER BY id DESC LIMIT 200
        """, (session.get("institution"), action, action_like, actor, actor_like)).fetchall()

    return render_template("audit.html", logs=logs, workflow_events=workflow_events,
        workflow_integrity=verify_chain(session.get("institution", "")), action=action, actor=actor)


# ---------------------------------------------------------
# Health check
# ---------------------------------------------------------

@app.route("/health")
def health():
    try:
        with connect_db() as db:
            db.execute("SELECT 1")

        return {
            "status": "ok",
            "database": "ok",
            "mode": "demo",
        }, 200

    except sqlite3.Error:
        return {
            "status": "error",
            "database": "unavailable",
        }, 503


# ---------------------------------------------------------
# Error handling
# ---------------------------------------------------------

@app.errorhandler(413)
def too_large(_error):
    if request.path.startswith("/source-datasets"):
        audit("source_dataset.import_rejected", "institution_source_dataset", "upload",
              "Source upload exceeded the configured request limit; file content omitted")
    flash("Upload exceeds the 2 MB limit.", "error")
    return redirect(url_for("source_datasets" if request.path.startswith("/source-datasets") else "imports"))


# Initialize the existing application database.
init_db()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
