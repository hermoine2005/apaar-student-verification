# APAAR SIH26263 deep implementation audit

Audit date: 2026-10-22  
Scope: active Flask/Jinja application, SQLite schemas, backend services, templates, tests, and synthetic runtime checks. README_dev.md labels itself a historical proposal; proposal material below is evaluated as a requirement, not evidence of implementation. The disconnected React/Express prototype is out of scope.

## Executive summary

The Flask app is a working synthetic-data prototype for student CRUD, local field checks, CSV import/export, human-reviewed duplicate candidates, institution-scoped review cases, and audit history. Ten focused pytest cases passed in this audit. The last known full-suite result is 47 passed in 55.40 seconds from the prior verification task; the full suite was not rerun here.

It is not a trustworthy source-verification system. The local verification action checks local fields only; no mock provider or lookup fixture exists; and the student API accepts arbitrary status strings. A fresh isolated runtime check confirmed an institution administrator could set verification_status to “Verified against source” and receive HTTP 200 without provider evidence. The detail page reveals the first four characters of the stored APAAR-like identifier, and the editor exposes the full value. Student CSV export omits APAAR ID but includes full institutional student code and email.

No live APAAR, ABC, DigiLocker, or government integration was attempted or found. No real student values, .env values, or database credentials were printed. Protected databases were inspected read-only. Runtime writes targeted .pytest_cache/apaar-test.db, per-test temporary databases, or one new GUID-named system-temp database. The disconnected apaar-platform-upgrade/ tree was not inspected or changed.

## Baseline and architecture

- Repository: C:/Users/rugve/OneDrive/Desktop/apaar-student-verification; branch main.
- Initial Git status: modified .gitignore, README.md, README_dev.md; deleted package.json; untracked .env.example, scripts, app.py, backend/, docs/, requirements.txt, static/, templates/, tests/, and apaar-platform-upgrade/. These pre-existing changes were preserved. This report is the only file added by this audit.
- Entry point: app.py. README startup after environment setup is python app.py; run.cmd also installs dependencies before launching and was not run. requirements.txt is the active Python dependency list.
- Database: APAAR_DB_PATH, defaulting to instance/apaar_demo.db. Importing app.py initializes schema; backend registration and the app’s final init_db() invoke initialization/migration logic. Startup may write schema/migration changes and a pre-upgrade backup, so runtime checks used isolated database paths. The legacy instance/apaar_backend.db has a separate API schema and is not configured as the active database.
- Main schema observed read-only: students includes apaar_id; workflow_cases, case_events, case_evidence, duplicate_candidates, import_jobs, audit_events, and legacy verification_cases exist. workflow_cases.assigned_to exists in SQLite but no assignment route or service uses it. Legacy DB schema differs (student_code, date_of_birth, etc.); it was not written.
- Seed code inserts four synthetic starter profiles and a seed audit event. The main DB aggregate status counts at inspection were Verified: 1, Pending: 2, Needs review: 1; no record values were selected or printed. The Verified seed has no source evidence.
- Roles: admin is mapped to institution_admin; other roles are operator, verifier, auditor. Flask sessions use database-backed role/institution lookup. API actor context is loaded from session username and the user row; identity headers are ignored.
- Main Jinja navigation: Review queue, Overview, Students, Import records, Audit history; admins also see Users & access and Archived records. No settings, notification, or integration-status screen exists.

## Requirements traceability matrix

Status meaning: IMPLEMENTED = verified in code and behavior; PARTIAL = some behavior exists, but acceptance criteria are missing; MISSING = no implementation found; UNVERIFIED = no safe evidence; BLOCKED = could not be safely checked. Features are not marked implemented based only on a README, dashboard label, or button.

| Requirement | Status | Evidence and behavior verification | Missing acceptance criteria | Severity | Recommended next action |
|---|---|---|---|---|---|
| 3.1 Student profile CRUD, search, filters, pagination, archive/restore | PARTIAL | app.py: student_form, students, student_detail, archive/restore; tests test_student_directory_filters_and_paginates and test_archive_restore_preserves_id_and_requires_conflict_resolution; focused end-to-end test passed. | No correction-request workflow or chronological academic-record history; server-side field-length/email validation is incomplete. | Medium | Add field validation and correction/history model. |
| 3.1 Institutional ID uniqueness | PARTIAL | students.institution_student_id has a global UNIQUE constraint; create/import/restore handle conflicts. | Requirement specifies institution-scoped uniqueness; global constraint can reject valid IDs in another institution. No ID format validation. | Medium | Make uniqueness tenant-scoped and define formats. |
| 3.2 Academic records and provenance | MISSING | Student schema has only course and semester; no academic_records or record_sources table. Schema source and both DB schemas inspected. | Exams, results, credits, source/timestamps, immutable source records, consistency checks, correction history. | High | Add separate academic-record and source-provenance entities. |
| 3.3 CSV upload, preview, row reporting, atomic confirmation, replay guard | IMPLEMENTED | app.py imports, confirm_import, import_errors; test_csv_preview_confirm_history_and_idempotency and test_import_confirmation_rolls_back_when_data_changes_after_preview; 2 MB cap, hash uniqueness, BEGIN IMMEDIATE. Focused import tests passed. | No full column mapping, larger streaming workflow, persisted failed-job history, or retention policy. Unknown columns are ignored. | Medium | Document the fixed schema; add mapping and failure states if required. |
| 3.3 CSV quality and formula safety | PARTIAL | backend/data_quality.py, row errors/warnings, spreadsheet_safe; test_csv_export_neutralizes_spreadsheet_formulas passed. API imports/dry-run does not write records. | Import does not check all academic consistency; error export includes full institutional code; malformed-content browser behavior not checked. | Medium | Expand field-level rules and test malformed/oversized files. |
| 3.4 Deterministic configurable verification rules | PARTIAL | validate_student_record() and verify_student() implement basic local checks. Quality tests cover explainability; local verification test exists. | Rules are not versioned/configurable; no approved reference data, academic consistency, source provenance, source-response/purpose match, or changed-since-review check. | High | Define versioned rule definitions and explicit inputs. |
| 3.4 Structured outcome, explanation, severity, evidence, source/time, manual-review flag | PARTIAL | Quality issues have code/severity/message/next_action; local case stores source, timestamp, summary/findings. | No structured per-rule outcome, version, evidence reference, or manual-review boolean; some findings are free text. | High | Persist typed rule-result records linked to evidence. |
| 3.4 Ten verification statuses and safe transitions | PARTIAL | Local action assigns Demo-validated or Needs review. A separate seven-state case model validates case transitions. | Only two specified verification statuses are controlled outcomes; API student patch accepts arbitrary status strings. | Critical | Define allowed states and transitions; reject unsupported or unauthorized changes. |
| 3.4 Failed/mock result cannot become authoritative | MISSING | No provider adapter/request handling. Isolated runtime check patched status to Verified against source and got HTTP 200 without provider evidence. | Only validated provider success may set source-verified; failure, stale, unauthorized, not-found, malformed, and mock outcomes must remain distinct. | Critical | Gate source-verified status on validated provider result plus evidence. |
| 3.5 Duplicate signals and human review | PARTIAL | backend/duplicates.py uses normalized/similar name, email match/difference, and same course; UI shows comparisons; decision requires reviewer and note. Duplicate tests passed previously; end-to-end focused test passed. | No institutional ID/admission-year signal; no precision/recall baseline. Candidate decision is not a merge workflow. | Medium | Retain review-only behavior; add representative false-positive fixtures. |
| 3.5 No automatic identity decision/delete and minimized comparison logs | IMPLEMENTED | Scan only creates candidates; no merge/delete path. Audit scan records counts, not compared names/emails. Human decision required; synthetic end-to-end test passed. | No merge behavior exists if it is later approved; do not infer one from decisions. | Low | Keep decisions advisory until a separately designed merge flow exists. |
| 3.6 Cases, transitions, reasons, timeline, evidence metadata | IMPLEMENTED | backend/cases.py and /api/v1/verification/cases routes; different reviewer required for resolve/close; timeline and case tests; focused end-to-end workflow passed. Evidence is metadata-only. | Cases link to students, not academic-record entities; no evidence file storage. | Medium | Add record-level links after academic-record model exists. |
| 3.6 Assignment, correction, reopen-on-change, retry | PARTIAL | assigned_to column exists but has no route/UI/service use. Resolved cases can return to in_review, but no source-change trigger. No correction request or provider retry path found. | Assignment authorization/history, correction states, change detection, safe integration retry. | High | Implement assignment/correction as audited events; retries after provider contracts. |
| 3.6 Case filters, age, priority, counts, tenant isolation | IMPLEMENTED | /api/v1/review and case_filters() use institution predicates, priority/status/age/reason and configured age bands; tenant/case-filter tests passed. | Queue caps at 200 cases and 100 work items; no pagination. | Low | Add pagination if expected volume exceeds caps. |
| 3.7 Dashboard metrics | PARTIAL | dashboard() queries total, Verified, Pending, Needs review, active cases, duplicates, quality findings, import previews, case-age bands, recent imports/activity; dashboard status test exists. | No separate source-verified or Demo-validated count, trends, average processing time, persisted failed imports, or classified security metric. Verified is not source-backed. | High | Replace ambiguous count with evidenced states; add required metrics. |
| 3.8 Audit/provenance | PARTIAL | audit_logs and hash-linked audit_events cover many student, account, case, duplicate, evidence, export and migration actions; integrity/tampering tests exist. | No correlation ID or result field; no provider/consent/source events; failed logins/authorization failures not recorded. Free-text case reason is copied into audit reason. Legacy audit_logs is not chained. | High | Add structured redacted events, correlation IDs, and security-failure coverage. |
| 3.9 Consent, purpose, lawful basis, withdrawal/expiry | MISSING | No consent model, route, service, or UI found; schema inspection confirms absence. | Capture, enforce, expire and withdraw permissions; explain requested fields and purpose. | High | Define applicable authorization/consent model before optional provider operations. |
| 3.10 Reports and exports | PARTIAL | Student export is institution/role scoped, formula-safe and omits APAAR; case CSV has filters, minimal fields, formula safety and audit event. Focused export tests passed. | Student export is unfiltered/unbounded and includes full student code/email; no source reference or generation timestamp. Import error export includes student code. | High | Minimize/mask output; add filters, limits and consistent export audit. |
| 3.11 Notifications | MISSING | No notification model/routes/UI; README calls this optional. | In-app pending/correction/import/provider/assignment notices. | Low | Defer until case/provider state is stable. |
| 9 Synthetic provider and safe failure contract | MISSING | No provider interface, fixture lookup dataset, integration job table, or /api/v1/integrations routes found. | Deterministic success, not-found, inconclusive, unauthorized, rate-limit, timeout, malformed, stale, unavailable responses. | High | Build provider-independent mock adapter and contract tests; no live calls. |
| 9 Official APAAR/ABC/DigiLocker access | UNVERIFIED | No integration code or credentials used; README correctly says no official service is contacted. | Approval, sandbox, credentials, provider contract, and allowed purpose are not established. | Low | Keep disabled until access is independently authorized and documented. |
| 10 Versioned API contracts, validation, pagination, safe errors | PARTIAL | Flask API under /api/v1; session/role and tenant-scoped queries; focused auth/tenant tests passed. Route list below. | Differs from proposed contracts; fixed LIMITs, no general pagination/OpenAPI/rate limits; JSON non-object shapes can raise errors; arbitrary status accepted. | High | Validate JSON shapes/statuses; add pagination and API schema docs. |
| 12 Authentication, roles, CSRF, tenant/object access | PARTIAL | Werkzeug password hashing, session login/logout, CSRF on state-changing methods, role decorators, tenant predicates. Focused login, CSRF, forged-header, tenant and export tests passed. | Login throttle is process-local; failed auth/access denials not audited; cookie Secure is opt-in. Browser role controls not manually checked. | Medium | Use shared production rate limiting, secure-cookie config, authorization-failure events. |
| 13 Privacy/security controls | PARTIAL | API student GET and student CSV omit APAAR; tested audit metadata omits field values; response security headers present. Runtime check confirms detail shows first four characters, not the full seeded ID. | Full APAAR value stored plaintext and exposed in editor; first four are not mask characters; no retention policy or consent flow. | High | Minimize/protect storage and mask every view/API/export; define retention. |
| 11 UI, accessibility, responsive and end-to-end behavior | UNVERIFIED | Flask test-client renders pages and links; navigation source inspected. No browser session was available; no authenticated browser workflow was automated. | Browser form, responsive, keyboard, loading, visual and role-control checks; no settings/integration screen or mapping wizard. | Medium | Human/browser walkthrough on a fresh synthetic instance. |
| 14 Testing strategy | PARTIAL | Ten focused tests run in this audit; prior full-suite result 47/47, not rerun. No provider contract or browser E2E tests found. | Provider failure, status-injection regression, mapping, malformed input, and some privilege/error paths. | Medium | Add focused tests with each implementation milestone. |
| 5–8 Proposed React/Express/PostgreSQL stack and normalized entities | MISSING | Active root is Flask/Jinja/SQLite. README_dev and README state React/Express prototype is disconnected; this is a historical architecture target, not the active app. | Proposed academic_records, record_sources, consent_records, validation_rules, integration_jobs, notifications absent. | Low | Implement missing domain behavior in active app before considering a stack migration. |
| 19 Definition of Done / 20 success metrics | PARTIAL | Synthetic CRUD/import/review and tests exist; official integration is not claimed. | Academic records/provenance, correct verification categories, fully masked identifiers, deployment proof and repeatable accuracy/performance baselines. | High | Gate demo completion on P0/P1 milestones; measure against synthetic fixtures. |

## Functional findings

### Rules and duplicate detection found

backend/data_quality.py::validate_student_record() checks: required institutional ID; ID length ≤80; duplicate-ID flag; required name; name length ≤160; email syntax/length; course ≤160; semester ≤40; APAAR ID ≤120; notes ≤1000; missing course/semester warnings; similar-name, duplicate-email, and pending-candidate warnings. Its output contains code, severity, message, next_action.

app.py::verify_student() separately checks required ID/name/institution, missing course/semester, exact normalized name plus institution, and identifier presence. It writes Needs review when findings exist, otherwise Demo-validated; creates a local-validation case and says no official lookup occurred. It does not use validate_student_record() to produce the verification outcome, so the quality panel/import rules and verification button are not one engine.

backend/duplicates.py::scan() scopes by institution; signals use normalized exact/similar name, same/different email, and same course if names are similar. It uses a configurable fuzzy-name threshold. It does not compare institutional ID or admission year and never merges/deletes. Human decisions are same_person, different_people, needs_evidence (API) and corresponding review decisions in the UI.

### Ten required statuses

| Required status | Active implementation |
|---|---|
| Draft | Missing |
| Pending verification | Missing as exact state; student Pending is a generic initial label |
| In progress | Partial semantic analogue: case in_review, not a student verification status |
| Verified against source | Missing as controlled outcome; arbitrary API status accepted (critical risk) |
| Demo-validated | Implemented for clean local checks only |
| Needs review | Implemented when local findings exist |
| Discrepancy detected | Missing as controlled status |
| Failed to verify | Missing as controlled status; Failed is only a directory filter option |
| Expired or stale | Missing |
| Cancelled | Missing |

The separate case state model is open, in_review, waiting_for_evidence, escalated, resolved, closed, recorded. Its service validates transitions and requires a reason and a different reviewer for resolve/close. These are case states, not the ten verification statuses or student categories.

### API routes found under /api/v1

GET /health; GET/POST /students; GET /students/<id>; PUT/PATCH /students/<id>; POST /imports/dry-run; GET /duplicates/candidates; POST /duplicates/candidates/<id>/decision; POST /duplicates/scan; GET/POST /verification/cases; POST /verification/cases/<id>/transition; GET /verification/cases/<id>/timeline; POST /verification/cases/<id>/evidence; POST /verification/evidence/<id>/decision; GET /review; POST /review/cases; POST /review/candidates/<id>/decision; POST /review/cases/<id>/transition; GET /reports/cases.csv; GET /audit; GET /audit/integrity.

Proposed /api/v1/auth/*, /integrations/*, /dashboard/summary, /audit-logs, /reports/verification, academic-record and verification-request contracts are absent. Authentication uses Flask session /login and /logout; API clients reuse that session and CSRF token.

## Verification performed

Fresh focused pytest command (exit code 0):

    .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_app.py::test_login_and_dashboard tests/test_app.py::test_csrf_rejects_state_changes_without_token tests/test_app.py::test_filtered_case_export_is_authorized_scoped_and_formula_safe tests/test_app.py::test_csv_export_neutralizes_spreadsheet_formulas tests/test_backend_foundation.py::test_identity_headers_cannot_authenticate_or_select_tenant tests/test_backend_foundation.py::test_other_institution_cannot_view_student tests/test_backend_foundation.py::test_case_workspace_is_tenant_scoped_and_requires_authentication tests/test_backend_foundation.py::test_end_to_end_synthetic_sih_workflow tests/test_imports.py::test_csv_preview_confirm_history_and_idempotency tests/test_imports.py::test_import_confirmation_rolls_back_when_data_changes_after_preview

Result: 10 passed in 18.94s. Test configuration was inspected first: import-time DB path resolved to .pytest_cache/apaar-test.db, distinct from both protected databases; individual app/import fixtures use tmp_path DBs. No full suite was run in this audit.

A separate inline Flask-client check used a new GUID-named system-temp SQLite file and synthetic test account. It confirmed arbitrary status acceptance (HTTP 200), student CSV omits the APAAR column, and detail page shows the first four identifier characters but not the complete synthetic value. The temp DB path was asserted distinct from both protected database paths before app import.

Browser verification: UNVERIFIED. Computer-use inventory had no app/browser session. No authenticated browser workflow was attempted. Flask test-client rendering is not equivalent to browser, responsive, keyboard, or visual verification.

## Critical correctness and security risks

1. **Critical — unsupported authoritative status:** backend/routes.py::students_update() accepts arbitrary verification_status. Fresh isolated runtime check proved Verified against source is accepted without provider data. The seeded Verified record is also unsupported by source evidence, although UI labels stored statuses internal/demo-only.
2. **High — APAAR-like identifier exposure:** full field is stored plaintext; first four characters are shown and editor form exposes the full value. Student export and API GET omit it, but masking/protected storage is incomplete.
3. **High — provenance/audit gaps:** no source records or provider correlation/result fields; failed login/authorization denials are not structured audit events. Free-text case reason is copied into audit reason and may contain sensitive content.
4. **Medium — global student-ID uniqueness:** global SQL UNIQUE is stricter than institution-scoped requirement.
5. **Medium — import/export limitations:** fixed columns, no mapping; student export has no filter/row limit and contains student code/email; failed attempts are not persisted.

No cross-institution access failure was observed in the focused student/case/export tests. That evidence covers those paths, not every object route.

## Recommended implementation order

1. Lock down status semantics. Verified against source must require a validated provider-success record with source, time, purpose, evidence and correlation ID; reject caller-supplied authoritative status changes. Separate demo/source outcomes in API, UI and metrics.
2. Protect identifiers and exports. Decide if full APAAR ID must be stored; if so, define reviewed protection and authorization. Mask all views/API outputs, restrict editor access, and minimize/cap exports.
3. Implement a provider-independent synthetic provider with deterministic success, not-found, inconclusive, unauthorized, rate-limit, timeout, malformed and stale fixtures. Do not connect to official services without authorization.
4. Implement versioned rules and structured outcomes, then academic-record/source-provenance entities and correction/change tracking.
5. Complete case assignment, correction requests, source-change reopening, rule-result evidence links and provider retry/error handling.
6. Complete dashboard metrics, audit result/correlation fields, security-failure events, consent/purpose handling and privacy-safe reporting.
7. Add focused contract/browser tests for provider failures, status injection, role boundaries, malformed input, exports and the synthetic end-to-end workflow.

Optional notifications, OCR, real provider integration and advanced analytics should follow the core milestones.

## Demo readiness and limitations

**Readiness:** suitable for a clearly labeled synthetic walkthrough of student records, local quality findings, CSV import, human-reviewed duplicate candidates, cases and audit history. **Not ready to demonstrate authoritative verification** until the status-injection path is closed and outcomes are evidence-backed. The app disclaims government connectivity, but the seeded Verified label and API behavior still need attention.

Limitations: no code or tests were added; no full-suite run in this audit; no live provider contacted; no deployment or production configuration verified. .env contents were not read. Main and legacy DBs were opened SQLite read-only for schema metadata and aggregate status counts; no personal-value rows were selected. Runtime test DB was created in system temp and is distinct from both protected DBs. Official integration/access status is not established by this audit.

