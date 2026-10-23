"""Safe, idempotent SQLite schema migrations shared by the application."""
import os
import sqlite3
from datetime import datetime, timezone


def migrate_student_identifier_scope(db_path: str) -> bool:
    """Replace global student-code uniqueness with institution-scoped uniqueness.

    Creates and validates a SQLite backup before rebuilding the students table.
    Existing duplicate codes within the same institution stop the migration before
    any schema changes; duplicates across institutions are allowed.
    """
    if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
        return False

    db = sqlite3.connect(db_path, timeout=30)
    try:
        row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='students'").fetchone()
        if not row:
            return False
        schema_sql = row[0] or ""
        marker = "student_identifier_scope_v1"
        already_applied = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_students_institution_code_ci'"
        ).fetchone()
        if already_applied:
            return False
        # If a prior custom schema already removed the global constraint, only add
        # the scoped index; the normal project schema has the legacy UNIQUE clause.
        has_global_unique = "institution_student_id TEXT NOT NULL UNIQUE" in schema_sql

        duplicate = db.execute("""SELECT lower(trim(institution)), lower(trim(institution_student_id)), COUNT(*)
            FROM students GROUP BY lower(trim(institution)), lower(trim(institution_student_id))
            HAVING COUNT(*) > 1 LIMIT 1""").fetchone()
        if duplicate:
            raise RuntimeError(
                "Cannot scope student IDs: duplicate institutional IDs already exist "
                "within one institution. Resolve those records and restart."
            )

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = f"{os.path.splitext(db_path)[0]}.pre-student-scope-{stamp}.db"
        backup = sqlite3.connect(backup_path)
        try:
            db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Student ID migration backup failed integrity check")
        finally:
            backup.close()

        db.commit()
        # SQLite can reject DROP TABLE / RENAME when triggers on other tables
        # refer to students: the trigger SQL is temporarily validated while the
        # referenced table is absent. Preserve those definitions, drop them inside
        # the migration transaction, and restore them after the replacement table
        # has its final name. This also keeps the migration safe for an app DB that
        # has already initialized backend triggers.
        student_dependent_triggers = [
            (trigger_name, trigger_sql)
            for trigger_name, trigger_sql in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL"
            ).fetchall()
            if "students" in trigger_sql.lower()
        ]
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.execute("BEGIN IMMEDIATE")
            for trigger_name, _trigger_sql in student_dependent_triggers:
                db.execute('DROP TRIGGER IF EXISTS "' + trigger_name.replace('"', '""') + '"')
            if has_global_unique:
                db.execute("""CREATE TABLE students_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    institution_student_id TEXT NOT NULL,
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
                )""")
                db.execute("""INSERT INTO students_new(
                    id,institution_student_id,full_name,institution,course,semester,apaar_id,email,
                    status,notes,created_at,updated_at,archived_at)
                    SELECT id,institution_student_id,full_name,institution,course,semester,apaar_id,email,
                    status,notes,created_at,updated_at,archived_at FROM students""")
                db.execute("DROP TABLE students")
                db.execute("ALTER TABLE students_new RENAME TO students")
            db.execute("CREATE INDEX IF NOT EXISTS idx_students_name ON students(full_name)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_students_status ON students(status)")
            db.execute("""CREATE UNIQUE INDEX uq_students_institution_code_ci
                ON students(lower(trim(institution)), lower(trim(institution_student_id)))""")
            for _trigger_name, trigger_sql in student_dependent_triggers:
                db.execute(trigger_sql)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")

        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                "Student ID migration detected foreign-key violations after rebuild; "
                f"backup preserved at {backup_path}"
            )
        return True
    finally:
        db.close()


def migrate_admissions_workflow_schema(db_path: str) -> bool:
    """Upgrade admissions constraints and preserve submission authorization links.

    This migration is idempotent. It backs up the live database before a table
    rebuild, performs the rebuild with foreign-key enforcement temporarily off,
    and validates row counts, SQLite integrity, and foreign-key relationships.
    """
    if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
        return False

    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        enrolment_schema = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='enrolments'"
        ).fetchone()
        submissions_exists = bool(db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='enrolment_submissions'"
        ).fetchone())
        submission_columns = {
            row[1] for row in db.execute("PRAGMA table_info(enrolment_submissions)")
        } if submissions_exists else set()
        if not enrolment_schema:
            return False

        schema_sql = enrolment_schema[0] or ""
        needs_rebuild = "'returned_for_correction'" not in schema_sql
        needs_column = submissions_exists and "authorization_id" not in submission_columns
        if not needs_rebuild and not needs_column:
            return False

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = f"{os.path.splitext(db_path)[0]}.pre-admissions-hardening-{stamp}.db"
        backup = sqlite3.connect(backup_path)
        try:
            db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"Admissions migration backup failed integrity check: {backup_path}")
        finally:
            backup.close()

        before_enrolments = db.execute("SELECT COUNT(*) FROM enrolments").fetchone()[0]
        before_submissions = db.execute("SELECT COUNT(*) FROM enrolment_submissions").fetchone()[0] if submission_columns else 0
        db.commit()
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            db.execute("BEGIN IMMEDIATE")
            if needs_rebuild:
                db.execute("""CREATE TABLE enrolments_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    institution TEXT NOT NULL,
                    student_id INTEGER NOT NULL,
                    allocation_id INTEGER NOT NULL,
                    institutional_enrolment_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN (
                        'draft','submitted','under_review','approved','rejected','withdrawn','returned_for_correction')),
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(institution, institutional_enrolment_id),
                    UNIQUE(student_id, allocation_id),
                    FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE RESTRICT,
                    FOREIGN KEY(allocation_id) REFERENCES intake_allocations(id) ON DELETE RESTRICT
                )""")
                db.execute("""INSERT INTO enrolments_new(
                    id,institution,student_id,allocation_id,institutional_enrolment_id,status,created_by,created_at,updated_at)
                    SELECT id,institution,student_id,allocation_id,institutional_enrolment_id,status,created_by,created_at,updated_at
                    FROM enrolments""")
                db.execute("DROP TABLE enrolments")
                db.execute("ALTER TABLE enrolments_new RENAME TO enrolments")
                db.execute("CREATE INDEX IF NOT EXISTS idx_enrolments_institution_status ON enrolments(institution,status,updated_at)")
            if needs_column:
                db.execute("ALTER TABLE enrolment_submissions ADD COLUMN authorization_id INTEGER REFERENCES data_use_authorizations(id) ON DELETE RESTRICT")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute("PRAGMA foreign_keys=ON")

        after_enrolments = db.execute("SELECT COUNT(*) FROM enrolments").fetchone()[0]
        after_submissions = db.execute("SELECT COUNT(*) FROM enrolment_submissions").fetchone()[0] if submission_columns else 0
        if before_enrolments != after_enrolments or before_submissions != after_submissions:
            raise RuntimeError(f"Admissions migration row-count mismatch; backup preserved at {backup_path}")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"Admissions migration integrity check failed; backup preserved at {backup_path}")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Admissions migration foreign-key check failed; backup preserved at {backup_path}")
        return True
    finally:
        db.close()
