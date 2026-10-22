import hashlib, hmac, json
from datetime import datetime, timezone
from .db import get_db

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def record_event(institution_id, actor_id, action, entity_type, entity_id, payload=None, reason=None):
    db = get_db()
    payload_json = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    prev = db.execute("SELECT event_hash FROM audit_events WHERE institution_id=? ORDER BY id DESC LIMIT 1",
                      (institution_id,)).fetchone()
    prev_hash = prev["event_hash"] if prev else "GENESIS"
    now = utc_now()
    material = "|".join([institution_id, actor_id, action, entity_type, entity_id, reason or "", payload_json, prev_hash, now])
    digest = hashlib.sha256(material.encode()).hexdigest()
    db.execute("INSERT INTO audit_events (institution_id,actor_id,action,entity_type,entity_id,reason,payload_json,previous_hash,event_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (institution_id, actor_id, action, entity_type, entity_id, reason, payload_json, prev_hash, digest, now))

def verify_chain(institution_id):
    rows = get_db().execute("""SELECT id,institution_id,actor_id,action,entity_type,entity_id,reason,
        payload_json,previous_hash,event_hash,created_at FROM audit_events
        WHERE institution_id=? ORDER BY id ASC""", (institution_id,)).fetchall()
    previous = "GENESIS"
    for row in rows:
        if not hmac.compare_digest(row["previous_hash"] or "", previous):
            return {"valid": False, "checked_events": len(rows), "first_invalid_event": row["id"]}
        material = "|".join([row["institution_id"], row["actor_id"], row["action"], row["entity_type"],
            row["entity_id"], row["reason"] or "", row["payload_json"], previous, row["created_at"]])
        expected = hashlib.sha256(material.encode()).hexdigest()
        if not hmac.compare_digest(row["event_hash"], expected):
            return {"valid": False, "checked_events": len(rows), "first_invalid_event": row["id"]}
        previous = row["event_hash"]
    return {"valid": True, "checked_events": len(rows), "first_invalid_event": None}
