import os, sqlite3
from flask import current_app, g
from .cases import ensure_case_schema, migrate_legacy_website_cases

SCHEMA = '''
CREATE TABLE IF NOT EXISTS duplicate_candidates (
 id TEXT PRIMARY KEY, institution_id TEXT NOT NULL, student_a_id INTEGER NOT NULL, student_b_id INTEGER NOT NULL,
 score INTEGER NOT NULL, signals_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending_review',
 decision_by TEXT, decision_note TEXT, decided_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(institution_id, student_a_id, student_b_id),
 FOREIGN KEY(student_a_id) REFERENCES students(id) ON DELETE RESTRICT,
 FOREIGN KEY(student_b_id) REFERENCES students(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS workflow_cases (
 id TEXT PRIMARY KEY, institution_id TEXT NOT NULL, student_id INTEGER NOT NULL, case_type TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal', reason TEXT NOT NULL,
 resolution_note TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS audit_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, institution_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, reason TEXT,
 payload_json TEXT NOT NULL, previous_hash TEXT, event_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_runs (
 id TEXT PRIMARY KEY, institution_id TEXT NOT NULL, student_id INTEGER NOT NULL, actor_id TEXT NOT NULL,
 ruleset_version TEXT NOT NULL, provider_name TEXT NOT NULL, provider_outcome TEXT NOT NULL,
 status TEXT NOT NULL, overall_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_verification_runs_scope ON verification_runs(institution_id,student_id,created_at);
CREATE TABLE IF NOT EXISTS verification_rule_results (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, institution_id TEXT NOT NULL,
 rule_id TEXT NOT NULL, rule_version TEXT NOT NULL, outcome TEXT NOT NULL, severity TEXT NOT NULL,
 explanation TEXT NOT NULL, evidence_refs_json TEXT NOT NULL, manual_review_required INTEGER NOT NULL,
 FOREIGN KEY(run_id) REFERENCES verification_runs(id) ON DELETE CASCADE
);
CREATE TRIGGER IF NOT EXISTS trg_duplicate_candidate_students_insert
BEFORE INSERT ON duplicate_candidates
WHEN NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_a_id)
  OR NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_b_id)
BEGIN SELECT RAISE(ABORT, 'duplicate candidate student not found'); END;
CREATE TRIGGER IF NOT EXISTS trg_duplicate_candidate_students_update
BEFORE UPDATE OF student_a_id,student_b_id ON duplicate_candidates
WHEN NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_a_id)
  OR NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_b_id)
BEGIN SELECT RAISE(ABORT, 'duplicate candidate student not found'); END;
CREATE TRIGGER IF NOT EXISTS trg_workflow_case_student_insert
BEFORE INSERT ON workflow_cases
WHEN NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_id)
BEGIN SELECT RAISE(ABORT, 'verification case student not found'); END;
CREATE TRIGGER IF NOT EXISTS trg_workflow_case_student_update
BEFORE UPDATE OF student_id ON workflow_cases
WHEN NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_id)
BEGIN SELECT RAISE(ABORT, 'verification case student not found'); END;
'''

def get_db():
    if "apaar_backend_db" not in g:
        # API workflow tables share the website's configured authoritative DB.
        path = current_app.config.get("APAAR_DB_PATH")
        if not path:
            os.makedirs(current_app.instance_path, exist_ok=True)
            path = os.path.join(current_app.instance_path, "apaar_demo.db")
        g.apaar_backend_db = sqlite3.connect(path)
        g.apaar_backend_db.row_factory = sqlite3.Row
        g.apaar_backend_db.execute("PRAGMA foreign_keys=ON")
    return g.apaar_backend_db

def close_db(_error=None):
    db = g.pop("apaar_backend_db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    ensure_case_schema(db)
    migrate_legacy_website_cases(db)
    candidate_columns = {row[1] for row in db.execute("PRAGMA table_info(duplicate_candidates)")}
    if "decided_at" not in candidate_columns:
        db.execute("ALTER TABLE duplicate_candidates ADD COLUMN decided_at TEXT")
    db.commit()
