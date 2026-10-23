import sqlite3

import pytest

from backend.migrations import migrate_student_identifier_scope


def make_legacy_db(path, *, duplicate_within_institution=False):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            institution_student_id TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            institution TEXT NOT NULL DEFAULT 'Demo Institution',
            course TEXT NOT NULL DEFAULT '', semester TEXT NOT NULL DEFAULT '',
            apaar_id TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending verification', notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT
        );
        CREATE TABLE related_records (
            id INTEGER PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id)
        );
    """)
    db.execute("INSERT INTO students(institution_student_id,full_name,institution,created_at,updated_at) VALUES('ROLL-1','Student A','Institution A','t','t')")
    db.execute("INSERT INTO students(institution_student_id,full_name,institution,created_at,updated_at) VALUES('ROLL-2','Student B','Institution B','t','t')")
    db.execute("INSERT INTO related_records(student_id) VALUES(1)")
    db.commit()
    if duplicate_within_institution:
        # Simulate legacy data that violates the desired case-insensitive rule.
        db.execute("DROP INDEX IF EXISTS uq_students_institution_code_ci")
        db.execute("ALTER TABLE students RENAME TO original_students")
        db.execute("""CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT, institution_student_id TEXT NOT NULL,
            full_name TEXT NOT NULL, institution TEXT NOT NULL, course TEXT NOT NULL DEFAULT '',
            semester TEXT NOT NULL DEFAULT '', apaar_id TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending verification', notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT
        )""")
        db.execute("INSERT INTO students SELECT * FROM original_students")
        db.execute("INSERT INTO students(institution_student_id,full_name,institution,created_at,updated_at) VALUES('roll-1','Student C','institution a','t','t')")
        db.commit()
    db.close()


def test_migration_allows_same_student_code_in_different_institutions_and_preserves_references(tmp_path):
    path = tmp_path / "legacy.db"
    make_legacy_db(path)

    assert migrate_student_identifier_scope(str(path)) is True
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("INSERT INTO students(institution_student_id,full_name,institution,created_at,updated_at) VALUES('ROLL-1','Student C','Institution C','t','t')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO students(institution_student_id,full_name,institution,created_at,updated_at) VALUES('roll-1','Student D','institution a','t','t')")
    db.rollback()
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("SELECT student_id FROM related_records").fetchone() == (1,)
    assert migrate_student_identifier_scope(str(path)) is False
    db.close()
    assert list(tmp_path.glob("legacy.pre-student-scope-*.db"))




def test_student_migration_preserves_triggers_that_reference_students(tmp_path):
    path = tmp_path / "triggered-legacy.db"
    make_legacy_db(path)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE duplicate_candidates (
            id TEXT PRIMARY KEY, student_a_id INTEGER NOT NULL, student_b_id INTEGER NOT NULL
        );
        CREATE TRIGGER trg_duplicate_candidate_students_insert
        BEFORE INSERT ON duplicate_candidates
        WHEN NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_a_id)
          OR NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_b_id)
        BEGIN SELECT RAISE(ABORT, 'duplicate candidate student not found'); END;
    """)
    db.commit()
    db.close()

    assert migrate_student_identifier_scope(str(path)) is True
    db = sqlite3.connect(path)
    trigger = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_duplicate_candidate_students_insert'"
    ).fetchone()
    assert trigger is not None
    db.execute("INSERT INTO duplicate_candidates(id,student_a_id,student_b_id) VALUES('valid',1,2)")
    with pytest.raises(sqlite3.IntegrityError, match="duplicate candidate student not found"):
        db.execute("INSERT INTO duplicate_candidates(id,student_a_id,student_b_id) VALUES('invalid',1,999)")
    db.rollback()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_migration_refuses_preexisting_case_insensitive_duplicates_without_losing_data(tmp_path):
    path = tmp_path / "duplicate.db"
    make_legacy_db(path, duplicate_within_institution=True)
    before = sqlite3.connect(path).execute("SELECT COUNT(*) FROM students").fetchone()[0]

    with pytest.raises(RuntimeError, match="duplicate institutional IDs"):
        migrate_student_identifier_scope(str(path))

    db = sqlite3.connect(path)
    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == before
    assert db.execute("SELECT COUNT(*) FROM students WHERE lower(institution_student_id)='roll-1'").fetchone()[0] == 2
    db.close()


def test_admissions_migration_preserves_rows_and_allows_return_for_correction(tmp_path):
    from backend.migrations import migrate_admissions_workflow_schema

    path = tmp_path / "admissions-legacy.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE students(id INTEGER PRIMARY KEY, institution TEXT NOT NULL);
        CREATE TABLE programmes(id INTEGER PRIMARY KEY, institution TEXT NOT NULL);
        CREATE TABLE intake_allocations(id INTEGER PRIMARY KEY, institution TEXT NOT NULL, programme_id INTEGER NOT NULL REFERENCES programmes(id));
        CREATE TABLE enrolments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, institution TEXT NOT NULL, student_id INTEGER NOT NULL,
            allocation_id INTEGER NOT NULL, institutional_enrolment_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','submitted','under_review','approved','rejected','withdrawn')),
            created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(institution,institutional_enrolment_id), UNIQUE(student_id,allocation_id),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE RESTRICT,
            FOREIGN KEY(allocation_id) REFERENCES intake_allocations(id) ON DELETE RESTRICT
        );
        CREATE TABLE enrolment_submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, institution TEXT NOT NULL, enrolment_id INTEGER NOT NULL,
            version INTEGER NOT NULL, status TEXT NOT NULL, submitted_by TEXT NOT NULL, submitted_at TEXT NOT NULL,
            reviewed_by TEXT, reviewed_at TEXT, review_note TEXT NOT NULL DEFAULT '', UNIQUE(enrolment_id,version),
            FOREIGN KEY(enrolment_id) REFERENCES enrolments(id) ON DELETE RESTRICT
        );
        CREATE TABLE data_use_authorizations(id INTEGER PRIMARY KEY);
        INSERT INTO students VALUES(1,'Campus A');
        INSERT INTO programmes VALUES(1,'Campus A');
        INSERT INTO intake_allocations VALUES(1,'Campus A',1);
        INSERT INTO enrolments VALUES(1,'Campus A',1,1,'ENR-1','submitted','operator','t','t');
        INSERT INTO enrolment_submissions VALUES(1,'Campus A',1,1,'submitted','operator','t',NULL,NULL,'');
    """)
    db.commit()
    db.close()

    assert migrate_admissions_workflow_schema(str(path)) is True
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    assert db.execute("SELECT COUNT(*) FROM enrolments").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM enrolment_submissions").fetchone()[0] == 1
    assert "returned_for_correction" in db.execute("SELECT sql FROM sqlite_master WHERE name='enrolments'").fetchone()[0]
    assert "authorization_id" in {r[1] for r in db.execute("PRAGMA table_info(enrolment_submissions)")}
    db.execute("UPDATE enrolments SET status='returned_for_correction' WHERE id=1")
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()
    assert migrate_admissions_workflow_schema(str(path)) is False
    assert list(tmp_path.glob("admissions-legacy.pre-admissions-hardening-*.db"))
