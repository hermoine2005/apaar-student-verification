import json, os, uuid
from difflib import SequenceMatcher
from .db import get_db
from .audit import utc_now, record_event

def norm(value):
    return " ".join((value or "").casefold().strip().split())

def scan(institution_id, actor_id):
    db = get_db()
    rows = db.execute("SELECT * FROM students WHERE institution=? AND archived_at IS NULL ORDER BY created_at", (institution_id,)).fetchall()
    try:
        name_threshold = min(1.0, max(0.5, float(os.environ.get("DUPLICATE_NAME_SIMILARITY", "0.88"))))
    except ValueError:
        name_threshold = 0.88
    count = 0
    for i, a in enumerate(rows):
        for b in rows[i+1:]:
            signals, score = [], 0
            name_a, name_b = norm(a["full_name"]), norm(b["full_name"])
            name_ratio = SequenceMatcher(None, name_a, name_b).ratio() if name_a and name_b else 0
            if name_a and name_a == name_b:
                signals.append("same_normalized_name"); score += 45
            elif name_ratio >= name_threshold:
                signals.append("similar_normalized_name"); score += 35
            if a["email"] and b["email"] and norm(a["email"]) == norm(b["email"]):
                signals.append("same_normalized_email"); score += 50
            elif a["email"] and b["email"]:
                signals.append("different_email_addresses")
            if name_ratio >= name_threshold and a["course"] and b["course"] and norm(a["course"]) == norm(b["course"]):
                signals.append("same_course"); score += 10
            if score < 35:
                continue
            left, right = sorted([str(a["id"]), str(b["id"])])
            cur = db.execute("INSERT OR IGNORE INTO duplicate_candidates (id,institution_id,student_a_id,student_b_id,score,signals_json,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), institution_id, left, right, min(score, 100), json.dumps(signals), "pending_review", utc_now()))
            count += cur.rowcount
    if count:
        record_event(institution_id, actor_id, "duplicate_scan.completed", "duplicate_scan", institution_id, {"new_candidates": count})
    db.commit()
    return count
