"""Shared verification case operations and additive legacy-history migration."""
import uuid
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _record_event(*args, **kwargs):
    # Lazy import avoids a cycle: audit reads its connection from backend.db.
    from .audit import record_event
    return record_event(*args, **kwargs)

CASE_STATES = {
    "open", "in_review", "waiting_for_evidence", "escalated",
    "resolved", "closed", "recorded",
}
TRANSITIONS = {
    "open": {"in_review", "waiting_for_evidence", "escalated", "closed"},
    "in_review": {"waiting_for_evidence", "resolved", "escalated", "open"},
    "waiting_for_evidence": {"in_review", "escalated", "closed"},
    "escalated": {"in_review", "resolved"},
    "resolved": {"closed", "in_review"},
    "closed": set(),
    "recorded": set(),
}


class CaseConflictError(ValueError):
    """Raised when a case changed after the caller loaded its current state."""


def ensure_case_schema(db):
    columns = {row[1] for row in db.execute("PRAGMA table_info(workflow_cases)")}
    additions = {
        "legacy_source": "TEXT",
        "legacy_id": "TEXT",
        "legacy_status": "TEXT",
        "summary": "TEXT",
        "findings": "TEXT",
        "source": "TEXT",
        "reviewer_id": "TEXT",
        "decision_at": "TEXT",
        "assigned_to": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE workflow_cases ADD COLUMN {name} {declaration}")
    db.executescript("""
        DROP TRIGGER IF EXISTS trg_workflow_case_student_insert;
        DROP TRIGGER IF EXISTS trg_workflow_case_student_update;
        CREATE TRIGGER trg_workflow_case_student_insert
        BEFORE INSERT ON workflow_cases
        WHEN NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_id AND institution=NEW.institution_id)
        BEGIN SELECT RAISE(ABORT, 'verification case student or institution not found'); END;
        CREATE TRIGGER trg_workflow_case_student_update
        BEFORE UPDATE OF student_id,institution_id ON workflow_cases
        WHEN NOT EXISTS(SELECT 1 FROM students WHERE id=NEW.student_id AND institution=NEW.institution_id)
        BEGIN SELECT RAISE(ABORT, 'verification case student or institution not found'); END;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_cases_legacy
            ON workflow_cases(legacy_source, legacy_id)
            WHERE legacy_source IS NOT NULL AND legacy_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            institution_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(case_id) REFERENCES workflow_cases(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_case_events_case ON case_events(case_id, id);
        CREATE TABLE IF NOT EXISTS case_evidence (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            institution_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            source TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'pending'
                CHECK(review_status IN ('pending','accepted','rejected')),
            reviewer_id TEXT,
            decision_at TEXT,
            checksum TEXT,
            description TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(case_id) REFERENCES workflow_cases(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_case_evidence_case ON case_evidence(case_id, uploaded_at);
        CREATE TRIGGER IF NOT EXISTS trg_case_events_scope_insert
        BEFORE INSERT ON case_events
        WHEN NOT EXISTS(SELECT 1 FROM workflow_cases WHERE id=NEW.case_id AND institution_id=NEW.institution_id)
        BEGIN SELECT RAISE(ABORT, 'case event institution mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS trg_case_evidence_scope_insert
        BEFORE INSERT ON case_evidence
        WHEN NOT EXISTS(SELECT 1 FROM workflow_cases WHERE id=NEW.case_id AND institution_id=NEW.institution_id)
        BEGIN SELECT RAISE(ABORT, 'case evidence institution mismatch'); END;
    """)


def migrate_legacy_website_cases(db):
    """Copy website validation history once, retaining source rows and IDs in a map."""
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "verification_cases" not in tables:
        return 0
    db.execute("SAVEPOINT migrate_legacy_website_cases")
    migrated = 0
    try:
        rows = db.execute("""
            SELECT v.id, v.student_id, v.status, v.summary, v.findings, v.source, v.created_at,
                   s.institution
            FROM verification_cases v LEFT JOIN students s ON s.id=v.student_id
            ORDER BY v.id
        """).fetchall()
        for row in rows:
            if not row[7]:
                raise ValueError(f"Legacy verification row {row[0]} has no valid student institution")
            legacy_id = str(row[0])
            exists = db.execute(
                "SELECT id FROM workflow_cases WHERE legacy_source='website' AND legacy_id=?",
                (legacy_id,),
            ).fetchone()
            if exists:
                continue
            canonical_id = f"legacy-web:{legacy_id}"
            collision = db.execute("SELECT id FROM workflow_cases WHERE id=?", (canonical_id,)).fetchone()
            if collision:
                raise ValueError(f"Canonical case ID collision for legacy verification row {legacy_id}")
            old_status = str(row[2] or "")
            folded = old_status.casefold().strip()
            state = "open" if folded in {"needs review", "pending"} else "recorded"
            reason = str(row[3] or "Legacy local validation")
            created = str(row[6] or _now())
            db.execute("""
                INSERT INTO workflow_cases (
                    id,institution_id,student_id,case_type,status,priority,reason,
                    created_by,created_at,updated_at,legacy_source,legacy_id,
                    legacy_status,summary,findings,source
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                canonical_id, row[7], row[1], "legacy_local_validation", state,
                "normal", reason, "migration", created, created, "website",
                legacy_id, old_status, row[3], row[4], row[5],
            ))
            db.execute("""
                INSERT INTO case_events
                    (case_id,institution_id,actor_id,event_type,to_status,note,created_at)
                VALUES(?,?,?,'case.migrated',?,?,?)
            """, (canonical_id, row[7], "migration", state,
                  f"Preserved legacy local-validation outcome: {old_status}", created))
            _record_event(row[7], "migration", "verification_case.migrated",
                         "verification_case", canonical_id,
                         {"legacy_source": "website", "legacy_id": legacy_id,
                          "mapped_status": state})
            migrated += 1
        db.execute("RELEASE SAVEPOINT migrate_legacy_website_cases")
        return migrated
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT migrate_legacy_website_cases")
        db.execute("RELEASE SAVEPOINT migrate_legacy_website_cases")
        raise


def create_case(db, *, institution_id, student_id, case_type, reason, actor_id,
                priority="normal", initial_status="open", summary=None,
                findings=None, source=None):
    student = db.execute(
        "SELECT id FROM students WHERE id=? AND institution=? AND archived_at IS NULL",
        (student_id, institution_id),
    ).fetchone()
    if not student:
        raise LookupError("Student not found in this institution")
    case_id, timestamp = str(uuid.uuid4()), _now()
    db.execute("""
        INSERT INTO workflow_cases
            (id,institution_id,student_id,case_type,status,priority,reason,created_by,
             created_at,updated_at,summary,findings,source)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (case_id, institution_id, student_id, case_type, initial_status, priority,
          reason, actor_id, timestamp, timestamp, summary, findings, source))
    db.execute("""
        INSERT INTO case_events
            (case_id,institution_id,actor_id,event_type,to_status,note,created_at)
        VALUES(?,?,?,'case.created',?,?,?)
    """, (case_id, institution_id, actor_id, initial_status, reason, timestamp))
    _record_event(institution_id, actor_id, "verification_case.created",
                 "verification_case", case_id,
                 {"student_id": str(student_id), "case_type": case_type}, reason)
    return case_id


def transition_case(db, *, case_id, institution_id, actor_id, role, target, note,
                    expected_updated_at=None):
    if role not in {"verifier", "institution_admin"}:
        raise PermissionError("Only an authorized reviewer may transition a case")
    case = db.execute(
        "SELECT * FROM workflow_cases WHERE id=? AND institution_id=?",
        (case_id, institution_id),
    ).fetchone()
    if not case:
        raise LookupError("Case not found")
    if expected_updated_at and expected_updated_at != case["updated_at"]:
        raise CaseConflictError("Case changed since it was opened; refresh and review the latest history")
    if target not in TRANSITIONS.get(case["status"], set()):
        raise ValueError("Invalid case status transition")
    note = (note or "").strip()
    if target in {"resolved", "closed"} and not 8 <= len(note) <= 1000:
        raise ValueError("A resolution or closure note of 8–1000 characters is required")
    if target in {"resolved", "closed"} and case["created_by"] == actor_id:
        raise PermissionError("A different reviewer must resolve or close the case")
    if target in {"resolved", "closed"} and case["assigned_to"] and case["assigned_to"] != actor_id:
        raise PermissionError("Only the assigned reviewer may resolve or close this case")
    timestamp = _now()
    cursor = db.execute("""
        UPDATE workflow_cases SET status=?,resolution_note=?,reviewer_id=?,decision_at=?,updated_at=?
        WHERE id=? AND institution_id=? AND status=? AND updated_at=?
    """, (target, note or None, actor_id, timestamp, timestamp, case_id,
          institution_id, case["status"], case["updated_at"]))
    if cursor.rowcount != 1:
        raise CaseConflictError("Case changed while this action was being saved; refresh and try again")
    db.execute("""
        INSERT INTO case_events
            (case_id,institution_id,actor_id,event_type,from_status,to_status,note,created_at)
        VALUES(?,?,?,'case.transitioned',?,?,?,?)
    """, (case_id, institution_id, actor_id, case["status"], target, note or None, timestamp))
    _record_event(institution_id, actor_id, "verification_case.transitioned",
                 "verification_case", case_id,
                 {"from": case["status"], "to": target}, note)
    return case


def assign_case(db, *, case_id, institution_id, actor_id, role, assignee):
    """Assign an institution case to an active reviewer and preserve history."""
    if role != "institution_admin":
        raise PermissionError("Only an institution administrator may assign cases")
    assignee = (assignee or "").strip()
    if len(assignee) > 80:
        raise ValueError("Reviewer selection is invalid")
    case = db.execute(
        "SELECT id,assigned_to,status FROM workflow_cases WHERE id=? AND institution_id=?",
        (case_id, institution_id),
    ).fetchone()
    if not case:
        raise LookupError("Case not found")
    if case["status"] in {"resolved", "closed", "recorded"}:
        raise ValueError("Completed cases cannot be assigned")
    if assignee:
        reviewer = db.execute(
            "SELECT username FROM users WHERE username=? AND institution=? AND role='verifier' AND is_active=1",
            (assignee, institution_id),
        ).fetchone()
        if not reviewer:
            raise ValueError("Select an active verifier in this institution")
    previous = case["assigned_to"] or ""
    if previous == assignee:
        raise ValueError("Case is already assigned to that reviewer")
    timestamp = _now()
    cursor = db.execute(
        "UPDATE workflow_cases SET assigned_to=?,updated_at=? WHERE id=? AND institution_id=? AND COALESCE(assigned_to,'')=? AND status NOT IN ('resolved','closed','recorded')",
        (assignee or None, timestamp, case_id, institution_id, previous),
    )
    if cursor.rowcount != 1:
        raise ValueError("Case assignment changed; refresh the queue and try again")
    action = "case.unassigned" if not assignee else ("case.assigned" if not previous else "case.reassigned")
    note = f"{previous or 'Unassigned'} -> {assignee or 'Unassigned'}"
    db.execute("""INSERT INTO case_events
        (case_id,institution_id,actor_id,event_type,note,created_at)
        VALUES(?,?,?,?,?,?)""", (case_id, institution_id, actor_id, action, note, timestamp))
    _record_event(institution_id, actor_id, action, "verification_case", case_id,
                  {"previous_assignee": previous or None, "assignee": assignee or None})
    return {"case_id": case_id, "previous_assignee": previous or None,
            "assignee": assignee or None, "action": action, "created_at": timestamp}


def add_evidence(db, *, case_id, institution_id, actor_id, evidence_type,
                 source, description, checksum=None):
    import re
    case = db.execute(
        "SELECT id FROM workflow_cases WHERE id=? AND institution_id=?",
        (case_id, institution_id),
    ).fetchone()
    if not case:
        raise LookupError("Case not found")
    evidence_type = (evidence_type or "").strip()
    source = (source or "").strip()
    description = (description or "").strip()
    if not 2 <= len(evidence_type) <= 80 or not 2 <= len(source) <= 200:
        raise ValueError("Evidence type and source are required (2–80 and 2–200 characters)")
    if len(description) > 1000:
        raise ValueError("Evidence description must be at most 1000 characters")
    if checksum and not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
        raise ValueError("Checksum must be a 64-character SHA-256 hex digest")
    evidence_id, timestamp = str(uuid.uuid4()), _now()
    db.execute("""
        INSERT INTO case_evidence
            (id,case_id,institution_id,evidence_type,source,uploaded_by,uploaded_at,
             review_status,checksum,description)
        VALUES(?,?,?,?,?,?,?,'pending',?,?)
    """, (evidence_id, case_id, institution_id, evidence_type, source,
          actor_id, timestamp, checksum.lower() if checksum else None, description))
    db.execute("""
        INSERT INTO case_events
            (case_id,institution_id,actor_id,event_type,note,created_at)
        VALUES(?,?,?,'evidence.added',?,?)
    """, (case_id, institution_id, actor_id,
          f"Evidence metadata added: {evidence_type} from {source}", timestamp))
    _record_event(institution_id, actor_id, "verification_evidence.added",
                 "verification_evidence", evidence_id,
                 {"case_id": case_id, "evidence_type": evidence_type,
                  "has_checksum": bool(checksum)})
    return evidence_id


def decide_evidence(db, *, evidence_id, institution_id, actor_id, decision, note):
    if decision not in {"accepted", "rejected"}:
        raise ValueError("Evidence decision must be accepted or rejected")
    note = (note or "").strip()
    if not 8 <= len(note) <= 1000:
        raise ValueError("Evidence decision reason must be 8–1000 characters")
    evidence = db.execute("""
        SELECT e.*,c.status AS case_status FROM case_evidence e
        JOIN workflow_cases c ON c.id=e.case_id AND c.institution_id=e.institution_id
        WHERE e.id=? AND e.institution_id=?
    """, (evidence_id, institution_id)).fetchone()
    if not evidence:
        raise LookupError("Evidence not found")
    if evidence["review_status"] != "pending":
        raise ValueError("Evidence has already been reviewed")
    if evidence["uploaded_by"] == actor_id:
        raise PermissionError("A different reviewer must decide on submitted evidence")
    timestamp = _now()
    db.execute("""
        UPDATE case_evidence SET review_status=?,reviewer_id=?,decision_at=?
        WHERE id=? AND institution_id=? AND review_status='pending'
    """, (decision, actor_id, timestamp, evidence_id, institution_id))
    db.execute("""
        INSERT INTO case_events
            (case_id,institution_id,actor_id,event_type,note,created_at)
        VALUES(?,?,?,'evidence.reviewed',?,?)
    """, (evidence["case_id"], institution_id, actor_id,
          f"Evidence {decision}: {note}", timestamp))
    _record_event(institution_id, actor_id, "verification_evidence.reviewed",
                 "verification_evidence", evidence_id,
                 {"case_id": evidence["case_id"], "decision": decision}, note)
    return evidence
