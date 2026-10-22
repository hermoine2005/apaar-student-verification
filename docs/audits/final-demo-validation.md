# Final Demo Validation — SIH26263

**Validation date:** 2026-10-22 (local time, Asia/Kolkata)  
**Application state:** branch `main`, HEAD `b5e4aad`; worktree already contained user changes and untracked project files.  
**Verdict:** **DEMO READY WITH LIMITATIONS**

The active Flask/Jinja app completed a synthetic, authenticated HTTP walkthrough on a fresh disposable SQLite database. All eight mock scenarios persisted structured results; review, audit, dashboard, export, redaction, and institution-scope checks produced the results below. This was not a browser test. No official provider is integrated, and identifiers are redacted rather than encrypted.

## Environment and launch

- Windows PowerShell; Python **3.11.9** from the existing `.venv`. Existing dependencies were used; no package installation occurred.
- Code confirms `APAAR_DB_PATH` selects the SQLite database, `APAAR_PROVIDER=mock` enables the local synthetic adapter, and `APAAR_MOCK_SCENARIO` supplies its default scenario. `DEMO_ADMIN_PASSWORD` controls the first local admin password; the documented local demo account was used, but its password is intentionally omitted here.
- Database initialization ran on a newly generated path under `%TEMP%`: `C:\Users\rugve\AppData\Local\Temp\apaar-final-demo-b43e713e479a4296984ca2950a12545e.db`. No protected `instance` database was selected. Startup initialized the app and workflow schemas and applied the provenance migration.
- Actual launch settings/command (the password value is omitted):

  ```powershell
  $demoDb = Join-Path $env:TEMP ('apaar-final-demo-' + [guid]::NewGuid().ToString('N') + '.db')
  $env:APAAR_DB_PATH = $demoDb
  $env:APAAR_PROVIDER = 'mock'
  $env:APAAR_MOCK_SCENARIO = 'matched'
  $env:PORT = '5051'
  .\.venv\Scripts\python.exe app.py
  ```

- `GET /health`: **PASS**, HTTP 200, `status=ok`, `database=ok`. The Flask server started without a traceback. The mock adapter is local deterministic code and made no external calls.
- Browser capability check returned no available apps or browsers. Validation therefore used **HTTP requests to the running local Flask app**, plus read-only SQLite inspection; no live browser walkthrough is claimed.
- An initial request attempt on port 5000 did not authenticate against the intended fresh app. Port ownership could not be confirmed because process/network inspection was denied. Re-running on port 5051 succeeded; use the explicit port in the command above.

## End-to-end results

| Check | Status | Observed result |
|---|---|---|
| Local sign-in and dashboard | PASS | Documented demo sign-in authenticated; dashboard returned HTTP 200. |
| Student create, search, detail, edit page | PASS | Created synthetic `E2E-SYN-001`; directory search found it and detail/edit pages returned HTTP 200. Institution supplied by the session was used. |
| Health and database startup | PASS | Server started on the disposable DB; `/health` reported database ready. |
| `matched` | PASS | Persisted `Demo-validated`; structured result and `match` displayed; mock `authoritative=false`; manual review was false. |
| `mismatch` | PASS | Persisted `Discrepancy detected`; result displayed; human review required. |
| `unavailable` | PASS | Persisted `Failed to verify`; no success fallback; human review required. |
| `inconclusive` | PASS | Persisted `Needs review`; human review required. |
| `not_found` | PASS | Persisted `Discrepancy detected`; human review required. |
| `unauthorized` | PASS | Persisted `Failed to verify`; human review required. |
| `malformed` | PASS | Persisted `Failed to verify`; human review required. |
| `stale` | PASS | Persisted `Expired or stale`; human review required. |
| Structured persistence | PASS | Read-only DB inspection found 9 runs (the 8 scenarios plus a final matched check), all with ruleset `local-rules-1.0`, four per-rule result rows, explanations, and the corresponding provider outcomes. All mock results were non-authoritative; latest student status matched latest run. No full identifier appeared in structured results. |
| Direct status tampering | PASS | API `PATCH` attempting `Verified against source` returned **403**. Student status remained the prior non-authoritative state. Final matched mock run remained `Demo-validated`. |
| Unsupported legacy success label | PASS | Automated migration regression verified legacy `Verified` becomes `Needs review`. A separate regression verifies an unbacked `Demo-validated` label moves to review and is not included in the dashboard success count. Fresh demo seed now begins `Pending verification`. |
| Review queue and human decision | PASS | A review-required run appeared in the institution review queue. A separate verifier moved its case `open → in_review → resolved` with a reason. Timeline returned 3 workflow events and 3 linked audit events; resolution was by a different reviewer. |
| Audit trail | PASS | `/api/v1/audit` contained `verification.completed` events (9 recorded). Audit payloads and case timeline did not contain the synthetic full identifier. Audit integrity remains a hash-chain check, not an absolute tamper-proof guarantee. |
| Dashboard counts | PASS | After the final matched result, dashboard showed **1 Demo-validated** and **0 authoritative-source-verified**. The synthetic seed no longer inflates demo-success counts without a structured run. |
| Student and case exports | PASS | Student CSV and `/api/v1/reports/cases.csv` returned HTTP 200 and omitted the synthetic identifier. Other-institution exports contained no main-institution student/case data. |
| Import validation and errors | PASS | API dry-run rejected one invalid synthetic row and omitted its identifier. A real CSV preview upload produced an error CSV containing the row code but no APAAR value or `apaar_id` column. No import confirmation was performed. |
| Identifier redaction | PASS | Full synthetic identifier absent from student detail, edit form, student APIs, verification result, API dry-run result, import error CSV, audit responses, student CSV, and case CSV. The profile exposes only a masked suffix. |
| Institution isolation | PASS | A synthetic account for another institution received **404** for student read and update with a valid CSRF token; page access redirected without showing the student. Other-institution API student/case lists were empty and exports omitted the record. |
| Error handling | PASS | Unknown student read returned 404; status tampering returned 403; cross-tenant read/update returned 404. Responses tested did not expose application internals. Flask request logs contained request paths/statuses, not form values or identifiers. |
| Live browser walkthrough | BLOCKED | No browser or app surface was available through the browser automation inventory; HTTP validation was used instead. |
| Official provider verification | BLOCKED | No approved/authorized APAAR, ABC, or DigiLocker adapter or credentials exist. Mock results cannot be represented as source verification. |
| Encryption at rest | NOT RUN | Not implemented; masking, omission, role checks, and institution scoping were checked. |

## Automated checks and repository integrity

- Focused command: `\.venv\Scripts\python.exe -m pytest -q tests/test_verification_integrity.py tests/test_app.py::test_login_and_dashboard tests/test_app.py::test_archive_preserves_student_history_and_hides_record tests/test_app.py::test_additive_schema_upgrade_creates_verified_backup_and_preserves_rows` — **16 passed**, **0 failed**, **exit code 0**.
- Full suite: `\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` — **60 passed**, **0 failed**, **0 skipped**, **exit code 0** (`38.03s`). The pytest fixture and per-test `tmp_path` databases were synthetic; no protected database was configured.
- `git diff --check` — **PASS**, no whitespace errors. Git emitted only its existing LF-to-CRLF warning for `.gitignore`.
- Initial and final Git status retained pre-existing changes: modified `.gitignore`, `README.md`, `README_dev.md`; deleted `package.json`; and untracked `.env.example`, `INTEGRATE_UPDATE.cmd`, `apaar-platform-upgrade/`, `app.py`, `backend/`, `docs-INTEGRATION.txt`, `docs/`, `register.md`, `requirements.txt`, `run.cmd`, `static/`, `templates/`, and `tests/`. This validation added/updated project files but made no commit or push.
- Neither `instance/apaar_demo.db` nor `instance/apaar_backend.db` was selected or written. The disconnected `apaar-platform-upgrade/` directory was not modified; it remains present in the pre-existing untracked state.

## Fix made during validation

Live inspection found that the fresh database seeded a student with `Demo-validated` but no structured verification run. Startup migration now moves unsupported demo/source status labels to `Needs review`, records an audit entry, and requires matching latest structured provider evidence for dashboard success counts. The initial seed is now `Pending verification`. Focused migration/dashboard tests and the one post-change full suite passed.

## Remaining limitations and not-run items

- There is no official provider adapter, no authoritative verification outcome, and no official service access. Do not describe this demo as government verification.
- Identifiers are masked/omitted but are not encrypted at rest.
- The browser walkthrough was not run because no browser was available. HTTP covered the sign-in and workflows but does not establish browser rendering compatibility.
- Import preview and error reporting were exercised; import confirmation/rollback were not part of this final live walkthrough. Existing automated tests cover import confirmation and rollback.
- Default port 5000 could not be confirmed as available; port 5051 worked.

**Final verdict: DEMO READY WITH LIMITATIONS.** The local synthetic workflow is demonstrable over HTTP and passed the recorded functional/security checks. Official-source verification, encryption at rest, and an actual browser walkthrough remain unavailable or unimplemented.
