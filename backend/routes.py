import csv, io, json
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g, render_template, redirect, url_for, flash, current_app, Response
from .db import get_db
from .security import require_actor
from .audit import utc_now, record_event, verify_chain
from .duplicates import scan
from .cases import create_case, transition_case, assign_case, add_evidence, decide_evidence, TRANSITIONS, CASE_STATES
from .data_quality import validate_student_record
from .verification import provider_configuration

api = Blueprint("apaar_api", __name__)

def err(message, status=400, code="invalid_request"):
    return jsonify({"error": code, "message": message}), status

def asdict(row):
    return dict(row)

def payload():
    return request.get_json(silent=True) or request.form

def case_age_info(created_at, thresholds):
    """Return age in days and an internal review-target category, if parseable."""
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - created).days)
    except (TypeError, ValueError, OverflowError):
        return None, "Age unavailable"
    first, second = thresholds
    if days < first:
        return days, f"Under {first} days"
    if days < second:
        return days, f"{first}–{second - 1} days"
    return days, f"{second}+ days"

def _timeline_order(timestamp):
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return datetime.min.replace(tzinfo=timezone.utc)

def case_audit_history(db, case_id, institution_id):
    rows = db.execute("""SELECT id,actor_id,action,entity_type,entity_id,reason,created_at
        FROM audit_events WHERE institution_id=? AND (
            (entity_type='verification_case' AND entity_id=?) OR
            (entity_type='verification_evidence' AND entity_id IN
                (SELECT id FROM case_evidence WHERE case_id=? AND institution_id=?)))
        ORDER BY id""", (institution_id, case_id, case_id, institution_id)).fetchall()
    return sorted(rows, key=lambda row: (_timeline_order(row["created_at"]), row["id"]))

def case_filters(args, institution_id):
    """Build the same tenant-scoped case predicate for the queue and CSV report."""
    status = str(args.get("case_status", "active")).strip()
    priority = str(args.get("case_priority", "")).strip()
    age = str(args.get("case_age", "")).strip()
    query = str(args.get("case_q", "")).strip()[:160]
    where, values = " WHERE c.institution_id=?", [institution_id]
    if status == "active":
        where += " AND c.status IN ('open','in_review','waiting_for_evidence','escalated')"
    elif status in CASE_STATES:
        where += " AND c.status=?"
        values.append(status)
    elif status != "all":
        status = "active"
        where += " AND c.status IN ('open','in_review','waiting_for_evidence','escalated')"
    if priority in {"low", "normal", "high"}:
        where += " AND c.priority=?"
        values.append(priority)
    else:
        priority = ""
    if age in {"7", "30", "90"}:
        where += " AND julianday('now')-julianday(c.created_at)>=?"
        values.append(int(age))
    else:
        age = ""
    if query:
        where += " AND (c.reason LIKE ? OR c.summary LIKE ? OR c.case_type LIKE ?)"
        values.extend([f"%{query}%"] * 3)
    return where, values, status, priority, age, query

def csv_safe(value):
    text = str(value or "")
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text

@api.get("/review")
@require_actor("operator", "verifier", "institution_admin", "auditor")
def review_queue():
    db = get_db()
    work_type = request.args.get("work_type", "all").strip()
    if work_type not in {"all", "cases", "duplicates", "quality", "imports"}:
        work_type = "all"
    case_where, case_args, case_status, case_priority, case_age, case_query = case_filters(
        request.args, g.actor.institution_id)
    candidates = db.execute("""SELECT c.*, a.full_name AS name_a, a.institution_student_id AS code_a,
        a.course AS course_a, a.semester AS semester_a, a.email AS email_a,
        b.full_name AS name_b, b.institution_student_id AS code_b,
        b.course AS course_b, b.semester AS semester_b, b.email AS email_b
        FROM duplicate_candidates c
        JOIN students a ON a.id=c.student_a_id AND a.institution=c.institution_id AND a.archived_at IS NULL
        JOIN students b ON b.id=c.student_b_id AND b.institution=c.institution_id AND b.archived_at IS NULL
        WHERE c.institution_id=? ORDER BY c.status='pending_review' DESC, c.score DESC, c.created_at DESC""",
        (g.actor.institution_id,)).fetchall()
    signal_labels = {
        "same_normalized_name": "Names match after normalization",
        "similar_normalized_name": "Names are highly similar",
        "same_normalized_email": "Email addresses match",
        "different_email_addresses": "Email addresses differ",
        "same_course": "Course also matches",
    }
    candidates = [{**dict(row), "signal_explanations": [
        signal_labels.get(signal, "Other matching signal") for signal in json.loads(row["signals_json"])
    ], "field_comparisons": [
        {"label": label, "state": ("Missing on one or both records" if not row[left] or not row[right]
                                     else "Matches" if str(row[left]).casefold().strip() == str(row[right]).casefold().strip()
                                     else "Differs")}
        for label, left, right in (("Course", "course_a", "course_b"),
                                   ("Semester", "semester_a", "semester_b"),
                                   ("Email", "email_a", "email_b"))
    ]} for row in candidates]
    active_cases = db.execute("""SELECT c.id,c.case_type,c.status,c.priority,c.created_at,c.reason,
        s.id AS student_id,s.institution_student_id FROM workflow_cases c
        JOIN students s ON s.id=c.student_id AND s.institution=c.institution_id
        WHERE c.institution_id=? AND c.status IN ('open','in_review','waiting_for_evidence','escalated')
        ORDER BY c.updated_at DESC LIMIT 200""", (g.actor.institution_id,)).fetchall()
    active_case_count = db.execute("""SELECT COUNT(*) FROM workflow_cases WHERE institution_id=?
        AND status IN ('open','in_review','waiting_for_evidence','escalated')""", (g.actor.institution_id,)).fetchone()[0]
    pending_duplicates = [row for row in candidates if row["status"] == "pending_review"]
    pending_student_ids = {sid for candidate in pending_duplicates
                           for sid in (candidate["student_a_id"], candidate["student_b_id"])}
    quality_tasks = []
    quality_rows = db.execute("""SELECT * FROM students WHERE institution=? AND archived_at IS NULL
        ORDER BY updated_at DESC""", (g.actor.institution_id,)).fetchall()
    for row in quality_rows:
        issues = validate_student_record(dict(row), potential_duplicate=row["id"] in pending_student_ids)
        if issues:
            quality_tasks.append({"student_id": row["id"], "student_code": row["institution_student_id"],
                                  "issue_count": len(issues), "issue_codes": [issue["code"] for issue in issues[:3] ]})
    import_tasks = db.execute("""SELECT id,file_name,status,accepted_count,rejected_count,created_at
        FROM import_jobs WHERE institution=? AND status='preview' ORDER BY created_at DESC LIMIT 100""",
        (g.actor.institution_id,)).fetchall()
    pending_import_count = db.execute("SELECT COUNT(*) FROM import_jobs WHERE institution=? AND status='preview'",
                                      (g.actor.institution_id,)).fetchone()[0]
    work_counts = {"cases": active_case_count, "duplicates": len(pending_duplicates),
                   "quality": len(quality_tasks), "imports": pending_import_count}
    work_items = []
    if work_type in {"all", "cases"}:
        work_items.extend({"kind": "Case", "label": f"{row['case_type']} · {row['status'].replace('_', ' ')}",
                           "detail": f"Student record {row['institution_student_id']} · {row['priority']} priority",
                           "url": url_for("apaar_api.review_queue", case_status="active") + f"#case-{row['id']}"}
                          for row in active_cases)
    if work_type in {"all", "duplicates"}:
        work_items.extend({"kind": "Duplicate review", "label": f"Compare {row['code_a']} and {row['code_b']}",
                           "detail": f"{row['score']}% match signal · human decision pending",
                           "url": url_for("apaar_api.review_queue") + f"#candidate-{row['id']}"}
                          for row in pending_duplicates)
    if work_type in {"all", "quality"}:
        work_items.extend({"kind": "Record quality", "label": f"Record {row['student_code']}",
                           "detail": f"{row['issue_count']} finding(s): {', '.join(row['issue_codes'])}",
                           "url": url_for("student_detail", student_id=row["student_id"])}
                          for row in quality_tasks)
    if work_type in {"all", "imports"}:
        work_items.extend({"kind": "Import preview", "label": row["file_name"],
                           "detail": f"{row['accepted_count']} ready · {row['rejected_count']} rejected · confirmation pending",
                           "url": url_for("imports", job_id=row["id"])}
                          for row in import_tasks)
    work_items = work_items[:100]
    cases = db.execute("""SELECT c.*, s.full_name, s.institution_student_id
        FROM workflow_cases c JOIN students s ON s.id=c.student_id AND s.institution=c.institution_id"""
        + case_where + " ORDER BY c.updated_at DESC LIMIT 200", case_args).fetchall()
    case_events = {}
    case_audit_events = {}
    case_evidence = {}
    case_age_days = {}
    for case in cases:
        thresholds = current_app.config.get("CASE_AGE_THRESHOLDS_DAYS", (7, 30))
        case_age_days[case["id"]], _ = case_age_info(case["created_at"], thresholds)
        case_events[case["id"]] = sorted(db.execute(
            "SELECT * FROM case_events WHERE case_id=? AND institution_id=? ORDER BY id",
            (case["id"], g.actor.institution_id),
        ).fetchall(), key=lambda row: (_timeline_order(row["created_at"]), row["id"]))
        case_audit_events[case["id"]] = case_audit_history(db, case["id"], g.actor.institution_id)
        case_evidence[case["id"]] = db.execute(
            "SELECT * FROM case_evidence WHERE case_id=? AND institution_id=? ORDER BY uploaded_at",
            (case["id"], g.actor.institution_id),
        ).fetchall()
    students = db.execute("SELECT id,full_name,institution_student_id FROM students WHERE institution=? AND archived_at IS NULL ORDER BY full_name LIMIT 500",
        (g.actor.institution_id,)).fetchall()
    reviewers = db.execute("SELECT username FROM users WHERE institution=? AND role='verifier' AND is_active=1 ORDER BY username LIMIT 100",
        (g.actor.institution_id,)).fetchall()
    reviewer_workload = db.execute("SELECT assigned_to,COUNT(*) AS count FROM workflow_cases WHERE institution_id=? AND assigned_to IS NOT NULL AND status IN ('open','in_review','waiting_for_evidence','escalated') GROUP BY assigned_to",
        (g.actor.institution_id,)).fetchall()
    return render_template("review.html", candidates=candidates, cases=cases,
                           case_events=case_events, case_audit_events=case_audit_events, case_evidence=case_evidence,
                           students=students, reviewers=reviewers,
                           reviewer_workload={row["assigned_to"]: row["count"] for row in reviewer_workload},
                           case_transition_options=TRANSITIONS,
                           case_status=case_status, case_priority=case_priority,
                           case_age=case_age, case_query=case_query,
                           work_type=work_type, work_counts=work_counts, work_items=work_items,
                           selected_case_student=request.args.get("case_student", ""),
                           case_age_days=case_age_days,
                           case_age_categories={c["id"]: case_age_info(c["created_at"], current_app.config.get("CASE_AGE_THRESHOLDS_DAYS", (7, 30)))[1] for c in cases},
                           case_age_targets="Internal review target bands: under %s days / %s-%s days / %s+ days" % (
                               current_app.config.get("CASE_AGE_THRESHOLDS_DAYS", (7, 30))[0],
                               current_app.config.get("CASE_AGE_THRESHOLDS_DAYS", (7, 30))[0],
                               current_app.config.get("CASE_AGE_THRESHOLDS_DAYS", (7, 30))[1] - 1,
                               current_app.config.get("CASE_AGE_THRESHOLDS_DAYS", (7, 30))[1]))

@api.get("/reports/cases.csv")
@require_actor("operator", "verifier", "institution_admin", "auditor")
def export_cases():
    where, values, *_ = case_filters(request.args, g.actor.institution_id)
    rows = get_db().execute("SELECT c.id,c.case_type,c.priority,c.status,c.created_at,c.updated_at FROM workflow_cases c" + where + " ORDER BY c.updated_at DESC LIMIT 500", values).fetchall()
    thresholds = current_app.config.get("CASE_AGE_THRESHOLDS_DAYS", (7, 30))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["case_id", "reason_category", "priority", "status", "outcome", "created_at", "updated_at", "age_days", "age_category"])
    for row in rows:
        days, category = case_age_info(row["created_at"], thresholds)
        outcome = row["status"] if row["status"] in {"resolved", "closed", "recorded"} else "pending"
        writer.writerow([csv_safe(row["id"]), csv_safe(row["case_type"]), csv_safe(row["priority"]), csv_safe(row["status"]), csv_safe(outcome), csv_safe(row["created_at"]), csv_safe(row["updated_at"]), "" if days is None else days, csv_safe(category)])
    record_event(g.actor.institution_id, g.actor.user_id, "verification_cases.exported",
                 "verification_case_report", "filtered", {"row_count": len(rows)})
    get_db().commit()
    return Response(output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=case_report.csv"})

@api.post("/review/cases")
@require_actor("operator", "verifier", "institution_admin")
def review_create_case():
    data = payload()
    sid, typ, reason = str(data.get("student_id") or "").strip(), str(data.get("case_type") or "").strip(), str(data.get("reason") or "").strip()
    if not sid or not typ or len(typ) > 80 or len(reason) < 8 or len(reason) > 1000:
        flash("Choose a student and provide a case type and reason (8–1000 characters).", "error")
        return redirect(url_for("apaar_api.review_queue"))
    db = get_db()
    try:
        cid = create_case(db, institution_id=g.actor.institution_id,
                          student_id=sid, case_type=typ, reason=reason,
                          actor_id=g.actor.user_id)
        db.commit()
    except LookupError:
        db.rollback()
        flash("Student was not found in this institution.", "error")
        return redirect(url_for("apaar_api.review_queue"))
    flash("Review case created.", "success")
    return redirect(url_for("apaar_api.review_queue"))

@api.post("/review/candidates/<cid>/decision")
@require_actor("verifier", "institution_admin")
def review_candidate_decision(cid):
    data = payload()
    decision, note = data.get("decision"), str(data.get("note") or "").strip()
    if decision not in {"same_person", "different_people", "needs_evidence"} or not 8 <= len(note) <= 1000:
        flash("Select a decision and provide a note of 8–1000 characters.", "error")
        return redirect(url_for("apaar_api.review_queue"))
    db = get_db()
    cur = db.execute("UPDATE duplicate_candidates SET status=?,decision_by=?,decision_note=?,decided_at=? WHERE id=? AND institution_id=? AND status='pending_review'",
        (decision, g.actor.user_id, note, utc_now(), cid, g.actor.institution_id))
    if not cur.rowcount:
        flash("Candidate was not found or was already reviewed.", "error")
        return redirect(url_for("apaar_api.review_queue"))
    record_event(g.actor.institution_id, g.actor.user_id, "duplicate_candidate.decided", "duplicate_candidate", cid, {"decision": decision}, note)
    db.commit()
    flash("Duplicate review recorded. No records were merged.", "success")
    return redirect(url_for("apaar_api.review_queue"))

@api.post("/review/cases/<cid>/transition")
@require_actor("verifier", "institution_admin")
def review_case_transition(cid):
    data = payload()
    target, note = data.get("status"), str(data.get("note") or "").strip()
    db = get_db()
    try:
        transition_case(db, case_id=cid, institution_id=g.actor.institution_id,
                        actor_id=g.actor.user_id, role=g.actor.role,
                        target=target, note=note)
        db.commit()
    except (LookupError, ValueError, PermissionError) as exc:
        db.rollback()
        flash(str(exc), "error")
        return redirect(url_for("apaar_api.review_queue"))
    flash("Case status updated.", "success")
    return redirect(url_for("apaar_api.review_queue"))


@api.post("/review/cases/<cid>/assignment")
@require_actor("institution_admin")
def review_case_assignment(cid):
    data = payload()
    db = get_db()
    try:
        result = assign_case(db, case_id=cid, institution_id=g.actor.institution_id,
                             actor_id=g.actor.user_id, role=g.actor.role,
                             assignee=str(data.get("assignee") or ""))
        db.commit()
    except LookupError:
        db.rollback()
        if request.is_json:
            return err("Case not found", 404, "not_found")
        flash("Case was not found in this institution.", "error")
        return redirect(url_for("apaar_api.review_queue"))
    except PermissionError as exc:
        db.rollback()
        if request.is_json:
            return err(str(exc), 403, "forbidden")
        flash(str(exc), "error")
        return redirect(url_for("apaar_api.review_queue"))
    except ValueError as exc:
        db.rollback()
        if request.is_json:
            return err(str(exc))
        flash(str(exc), "error")
        return redirect(url_for("apaar_api.review_queue"))
    if request.is_json:
        return jsonify(result)
    flash("Case assignment saved and added to the audit timeline.", "success")
    return redirect(url_for("apaar_api.review_queue") + f"#case-{cid}")

@api.post("/duplicates/scan")
@require_actor("operator", "institution_admin")
def duplicates_scan():
    count = scan(g.actor.institution_id, g.actor.user_id)
    flash(f"Duplicate review scan completed. {count} new candidate(s) found.", "success")
    return redirect(url_for("apaar_api.review_queue"))

@api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "apaar-backend", "api_version": "v1"})

@api.get("/students")
@require_actor("operator", "verifier", "institution_admin", "auditor")
def students_list():
    rows = get_db().execute("SELECT * FROM students WHERE institution=? AND archived_at IS NULL ORDER BY updated_at DESC LIMIT 500",
                            (g.actor.institution_id,)).fetchall()
    items = [{"id": str(r["id"]), "institution_id": g.actor.institution_id,
              "student_code": r["institution_student_id"], "full_name": r["full_name"],
              "email": r["email"], "course": r["course"], "academic_year": r["semester"],
              "verification_status": ("Needs review" if r["status"] == "Verified" else r["status"]), "source_label": "shared_student_record",
              "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]
    return jsonify({"items": items, "count": len(items)})


@api.get("/students/<int:student_id>")
@require_actor("operator", "verifier", "institution_admin", "auditor")
def student_get(student_id):
    row = get_db().execute("""
        SELECT * FROM students WHERE id=? AND institution=? AND archived_at IS NULL
    """, (student_id, g.actor.institution_id)).fetchone()
    if not row:
        return err("Student not found in this institution", 404, "not_found")
    latest_run = get_db().execute("""SELECT provider_name,provider_outcome,status,overall_json,created_at
        FROM verification_runs WHERE institution_id=? AND student_id=? ORDER BY created_at DESC,id DESC LIMIT 1""",
        (g.actor.institution_id, student_id)).fetchone()
    external_provider = None
    if latest_run:
        try:
            stored = json.loads(latest_run["overall_json"] or "{}")
            provider = stored.get("provider", {})
            state = provider.get("state") or ("SIMULATED" if latest_run["provider_name"] in {"mock", "synthetic_mock"} else "NOT_CONFIGURED")
            external_provider = {"state": state, "provider": latest_run["provider_name"],
                "outcome": latest_run["provider_outcome"], "explanation": provider.get("explanation", ""),
                "authoritative": bool(provider.get("authoritative", False)) and latest_run["provider_name"] != "synthetic_mock",
                "manual_review_required": bool(provider.get("manual_review_required", True)), "checked_at": latest_run["created_at"]}
        except (TypeError, ValueError):
            external_provider = {"state": "FAILED", "provider": "unknown", "outcome": "invalid_stored_result",
                "explanation": "Stored provider result could not be read safely.", "authoritative": False,
                "manual_review_required": True, "checked_at": latest_run["created_at"]}
    latest_comparison = get_db().execute("""SELECT c.outcome,c.explanation,c.fields_json,c.dataset_version,c.created_at,d.name
        FROM institution_source_comparisons c JOIN institution_source_datasets d
          ON d.id=c.dataset_id AND d.institution=c.institution
        WHERE c.institution=? AND c.student_id=? ORDER BY c.created_at DESC,c.id DESC LIMIT 1""",
        (g.actor.institution_id, student_id)).fetchone()
    institution_comparison = None
    if latest_comparison:
        institution_comparison = {"source": "institution-provided dataset", "dataset_name": latest_comparison["name"],
            "dataset_version": latest_comparison["dataset_version"], "outcome": latest_comparison["outcome"],
            "explanation": latest_comparison["explanation"], "fields": json.loads(latest_comparison["fields_json"] or "{}"),
            "checked_at": latest_comparison["created_at"], "authoritative": False}
    return jsonify({
        "id": str(row["id"]), "institution_id": row["institution"],
        "student_code": row["institution_student_id"], "full_name": row["full_name"],
        "email": row["email"], "course": row["course"],
        "academic_year": row["semester"], "verification_status": ("Needs review" if row["status"] == "Verified" else row["status"]),
        "source_label": "shared_student_record", "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "external_provider_verification": external_provider,
        "external_provider_configuration": provider_configuration(),
        "institution_source_comparison": institution_comparison,
    })

@api.post("/students")
@require_actor("operator", "institution_admin")
def students_create():
    d = payload()
    code, name = str(d.get("student_code", "")).strip(), str(d.get("full_name", "")).strip()
    if not code or not name:
        return err("student_code and full_name are required")
    if len(code) > 80 or len(name) > 160:
        return err("student_code or full_name too long")
    record = {"institution_student_id": code, "full_name": name,
              "course": str(d.get("course") or ""), "semester": str(d.get("academic_year") or ""),
              "email": str(d.get("email") or ""), "apaar_id": str(d.get("apaar_id") or ""), "notes": str(d.get("notes") or "")}
    issues = validate_student_record(record)
    errors = [issue for issue in issues if issue["severity"] == "error"]
    if errors:
        return jsonify({"error": "validation_error", "message": "Student fields failed validation", "issues": errors}), 400
    db, now = get_db(), utc_now()
    try:
        cur = db.execute("INSERT INTO students (institution_student_id,full_name,institution,course,semester,email,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (code, name, g.actor.institution_id, str(d.get("course") or ""),
           str(d.get("academic_year") or ""), str(d.get("email") or ""),
           "Pending verification", "Created through shared API", now, now))
        sid = str(cur.lastrowid)
        record_event(g.actor.institution_id, g.actor.user_id, "student.created", "student", sid, {})
        db.commit()
    except Exception as ex:
        db.rollback()
        if "UNIQUE constraint failed" in str(ex):
            return err("Student code already exists in this institution", 409, "duplicate")
        raise
    return jsonify({"id": sid, "student_code": code, "verification_status": "Pending verification"}), 201

@api.put("/students/<int:student_id>")
@api.patch("/students/<int:student_id>")
@require_actor("operator", "institution_admin")
def students_update(student_id):
    data = payload()
    allowed = {"student_code", "full_name", "course", "academic_year", "email", "apaar_id", "notes"}
    if "verification_status" in (data or {}):
        return err("Verification status can only be changed by a verification run or authorized review", 403, "forbidden")
    if not data or set(data.keys()) - allowed:
        return err("Provide student fields using the documented API names")
    db = get_db()
    current = db.execute("SELECT * FROM students WHERE id=? AND institution=? AND archived_at IS NULL", (student_id, g.actor.institution_id)).fetchone()
    if not current:
        return err("Student not found in this institution", 404, "not_found")
    values = {
        "institution_student_id": str(data.get("student_code", current["institution_student_id"])).strip(),
        "full_name": str(data.get("full_name", current["full_name"])).strip(),
        "course": str(data.get("course", current["course"] or "")).strip(),
        "semester": str(data.get("academic_year", current["semester"] or "")).strip(),
        "email": str(data.get("email", current["email"] or "")).strip(),
        "apaar_id": str(data.get("apaar_id", current["apaar_id"] or "")).strip(),
        "notes": str(data.get("notes", current["notes"] or "")).strip(),
        "status": current["status"],
    }
    if not values["institution_student_id"] or len(values["institution_student_id"]) > 80:
        return err("student_code is required and must be at most 80 characters")
    if not values["full_name"] or len(values["full_name"]) > 160:
        return err("full_name is required and must be at most 160 characters")
    if len(values["email"]) > 254 or (values["email"] and "@" not in values["email"]):
        return err("email is invalid")
    issues = validate_student_record({"institution_student_id": values["institution_student_id"],
        "full_name": values["full_name"], "course": values["course"], "semester": values["semester"],
        "email": values["email"], "apaar_id": values["apaar_id"], "notes": values["notes"]})
    errors = [issue for issue in issues if issue["severity"] == "error"]
    if errors:
        return jsonify({"error": "validation_error", "message": "Student fields failed validation", "issues": errors}), 400
    try:
        db.execute("""UPDATE students SET institution_student_id=?,full_name=?,course=?,semester=?,email=?,
            apaar_id=?,notes=?,status=?,updated_at=? WHERE id=? AND institution=?""",
            (values["institution_student_id"], values["full_name"], values["course"], values["semester"],
             values["email"], values["apaar_id"], values["notes"], values["status"], utc_now(), student_id, g.actor.institution_id))
        record_event(g.actor.institution_id, g.actor.user_id, "student.updated", "student", str(student_id),
            {"fields": sorted(data.keys())})
        db.commit()
    except Exception as ex:
        db.rollback()
        if "UNIQUE constraint failed" in str(ex):
            return err("Student code already exists", 409, "duplicate")
        raise
    return jsonify({"id": str(student_id), "student_code": values["institution_student_id"],
        "full_name": values["full_name"], "verification_status": values["status"]})

@api.post("/imports/dry-run")
@require_actor("operator", "institution_admin")
def import_dry_run():
    d = payload()
    content = d.get("csv_text")
    if not isinstance(content, str) or not content.strip():
        return err("Provide csv_text")
    if len(content.encode("utf-8")) > 2_000_000:
        return err("CSV exceeds 2 MB demo limit", 413)
    reader = csv.DictReader(io.StringIO(content))
    headers = {str(h or "").strip() for h in (reader.fieldnames or [])}
    if not {"student_code", "full_name"}.issubset(headers):
        return err("CSV must include student_code and full_name headers")
    existing_rows = get_db().execute("SELECT institution_student_id FROM students WHERE institution=?", (g.actor.institution_id,)).fetchall()
    existing = {r["institution_student_id"].casefold().strip() for r in existing_rows}
    seen, accepted, rejected = set(), [], []
    for line, raw in enumerate(reader, start=2):
        row = {str(k or "").strip(): str(v or "").strip() for k, v in raw.items()}
        code, name = row.get("student_code", ""), row.get("full_name", "")
        issues = []
        if not code: issues.append("missing_student_code")
        if not name: issues.append("missing_full_name")
        if code and code.casefold() in existing: issues.append("student_code_already_exists")
        if code and code.casefold() in seen: issues.append("duplicate_code_in_file")
        if row.get("email") and "@" not in row["email"]: issues.append("invalid_email")
        if code: seen.add(code.casefold())
        item = {"line": line, "student_code": code, "full_name": name, "issues": issues}
        (rejected if issues else accepted).append(item)
    return jsonify({"mode": "dry_run", "accepted_count": len(accepted), "rejected_count": len(rejected),
                    "accepted": accepted, "rejected": rejected, "note": "No records were written."})

@api.get("/duplicates/candidates")
@require_actor("operator", "verifier", "institution_admin", "auditor")
def duplicates_list():
    db = get_db()
    rows = db.execute("SELECT * FROM duplicate_candidates WHERE institution_id=? ORDER BY score DESC, created_at DESC",
                      (g.actor.institution_id,)).fetchall()
    return jsonify({"items": [{**asdict(r), "signals": json.loads(r["signals_json"])} for r in rows]})

@api.post("/duplicates/candidates/<cid>/decision")
@require_actor("verifier", "institution_admin")
def duplicates_decide(cid):
    d = payload()
    decision, note = d.get("decision"), str(d.get("note") or "").strip()
    if decision not in {"same_person", "different_people", "needs_evidence"}:
        return err("decision must be same_person, different_people, or needs_evidence")
    if len(note) < 8:
        return err("Provide a decision note of at least 8 characters")
    db = get_db()
    cur = db.execute("UPDATE duplicate_candidates SET status=?,decision_by=?,decision_note=?,decided_at=? WHERE id=? AND institution_id=? AND status='pending_review'",
                     (decision, g.actor.user_id, note, utc_now(), cid, g.actor.institution_id))
    if cur.rowcount == 0:
        return err("Candidate not found or already decided", 404, "not_found")
    record_event(g.actor.institution_id, g.actor.user_id, "duplicate_candidate.decided", "duplicate_candidate", cid, {"decision": decision}, note)
    db.commit()
    return jsonify({"id": cid, "status": decision})

@api.get("/verification/cases")
@require_actor("operator", "verifier", "institution_admin", "auditor")
def cases_list():
    rows = get_db().execute("SELECT * FROM workflow_cases WHERE institution_id=? ORDER BY updated_at DESC LIMIT 500",
                            (g.actor.institution_id,)).fetchall()
    return jsonify({"items": [asdict(r) for r in rows]})

@api.post("/verification/cases")
@require_actor("operator", "verifier", "institution_admin")
def cases_create():
    d = payload()
    sid, typ, reason = str(d.get("student_id") or "").strip(), str(d.get("case_type") or "").strip(), str(d.get("reason") or "").strip()
    if not sid or not typ or len(typ) > 80 or not 8 <= len(reason) <= 1000:
        return err("student_id, case_type, and reason (8–1000 characters) are required")
    db = get_db()
    priority = d.get("priority") if d.get("priority") in {"low", "normal", "high"} else "normal"
    try:
        cid = create_case(db, institution_id=g.actor.institution_id,
                          student_id=sid, case_type=typ, reason=reason,
                          actor_id=g.actor.user_id, priority=priority)
        db.commit()
    except LookupError:
        db.rollback()
        return err("Student not found in this institution", 404, "not_found")
    return jsonify({"id": cid, "status": "open"}), 201

@api.post("/verification/cases/<cid>/transition")
@require_actor("verifier", "institution_admin")
def cases_transition(cid):
    d = payload()
    target, note = d.get("status"), str(d.get("note") or "").strip()
    db = get_db()
    try:
        transition_case(db, case_id=cid, institution_id=g.actor.institution_id,
                        actor_id=g.actor.user_id, role=g.actor.role,
                        target=target, note=note)
        db.commit()
    except LookupError:
        db.rollback()
        return err("Case not found", 404, "not_found")
    except PermissionError as exc:
        db.rollback()
        return err(str(exc), 403, "forbidden")
    except ValueError as exc:
        db.rollback()
        return err(str(exc))
    return jsonify({"id": cid, "status": target})


@api.get("/verification/cases/<cid>/timeline")
@require_actor("operator", "verifier", "institution_admin", "auditor")
def cases_timeline(cid):
    db = get_db()
    if not db.execute("SELECT id FROM workflow_cases WHERE id=? AND institution_id=?", (cid, g.actor.institution_id)).fetchone():
        return err("Case not found", 404, "not_found")
    events = sorted(db.execute("SELECT * FROM case_events WHERE case_id=? AND institution_id=? ORDER BY id", (cid, g.actor.institution_id)).fetchall(),
                    key=lambda row: (_timeline_order(row["created_at"]), row["id"]))
    evidence = db.execute("SELECT * FROM case_evidence WHERE case_id=? AND institution_id=? ORDER BY uploaded_at", (cid, g.actor.institution_id)).fetchall()
    audit_events = case_audit_history(db, cid, g.actor.institution_id)
    return jsonify({"events": [asdict(row) for row in events], "audit_events": [asdict(row) for row in audit_events], "evidence": [asdict(row) for row in evidence]})


@api.post("/verification/cases/<cid>/evidence")
@require_actor("operator", "institution_admin")
def cases_evidence_add(cid):
    d = payload()
    db = get_db()
    try:
        evidence_id = add_evidence(db, case_id=cid,
            institution_id=g.actor.institution_id, actor_id=g.actor.user_id,
            evidence_type=str(d.get("evidence_type") or ""),
            source=str(d.get("source") or ""),
            description=str(d.get("description") or ""),
            checksum=str(d.get("checksum") or "").strip() or None)
        db.commit()
    except LookupError:
        db.rollback()
        return err("Case not found", 404, "not_found")
    except ValueError as exc:
        db.rollback()
        return err(str(exc))
    return jsonify({"id": evidence_id, "review_status": "pending", "synthetic_metadata_only": True}), 201


@api.post("/verification/evidence/<evidence_id>/decision")
@require_actor("verifier", "institution_admin")
def evidence_decision(evidence_id):
    d = payload()
    db = get_db()
    try:
        decide_evidence(db, evidence_id=evidence_id,
            institution_id=g.actor.institution_id, actor_id=g.actor.user_id,
            decision=d.get("decision"), note=str(d.get("note") or ""))
        db.commit()
    except LookupError:
        db.rollback()
        return err("Evidence not found", 404, "not_found")
    except PermissionError as exc:
        db.rollback()
        return err(str(exc), 403, "forbidden")
    except ValueError as exc:
        db.rollback()
        return err(str(exc))
    return jsonify({"id": evidence_id, "review_status": d.get("decision")})

@api.get("/audit")
@require_actor("institution_admin", "auditor")
def audit_list():
    rows = get_db().execute("SELECT id,actor_id,action,entity_type,entity_id,reason,payload_json,previous_hash,event_hash,created_at FROM audit_events WHERE institution_id=? ORDER BY id DESC LIMIT 200",
                            (g.actor.institution_id,)).fetchall()
    return jsonify({"items": [{**asdict(r), "payload": json.loads(r["payload_json"])} for r in rows]})

@api.get("/audit/integrity")
@require_actor("institution_admin", "auditor")
def audit_integrity():
    return jsonify(verify_chain(g.actor.institution_id))
