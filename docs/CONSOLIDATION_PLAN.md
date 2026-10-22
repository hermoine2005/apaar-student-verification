# Consolidation Plan

Audit date: 2026-10-22

## Existing implementations

1. `app.py` is the established Flask/Jinja application. It has persistent SQLite storage, login, dashboard, student forms and detail pages, local verification, CSV import/export, audit logs, and a health endpoint.
2. `backend/` is a Flask API blueprint with student, import dry-run, duplicate review, verification case, and audit endpoints. Recent edits make API student operations use the root app's SQLite database and derive identity from the Flask session. The API has separate workflow/audit tables.
3. `apaar-platform-upgrade/` is a React/Vite UI and Express API prototype. Its API stores data in process memory and does not share authentication or persistence with Flask.
4. The root `package.json` was an earlier TypeScript/Postgres remnant with a failing placeholder test, no lockfile, empty workspace targets, and no runtime consumers. It has been removed after reference checks. `README_dev.md` remains a historical proposal with a pointer to the runnable root README.

## Retained implementation

Retain Flask/Jinja as the canonical application and `backend/` as its versioned API. They already share a process, can share one SQLite data model, and the website has the most complete persistent user-facing workflows. Do not discard the React/Express prototype or its unique UI work during this consolidation; keep it explicitly labeled as a disconnected prototype until its useful features can be migrated and it can be removed safely.

## Reuse and redundancy

- Reuse root templates, CSS, student routes, CSV paths, SQLite student table, and session login.
- Reuse API duplicate candidate functionality. `workflow_cases` is now the canonical case table and is surfaced in the main UI with shared IDs and tenant scope; legacy website local-validation history is mapped as documented in `CASE_MIGRATION_MAPPING.md`.
- Preserve the nested React/Express source and its documentation as prototype work. Avoid claiming it is the primary app.
- The unused root manifest was removed after reference checks. The nested React/Express workspace remains because its screen design is useful and has not yet been migrated; it is explicitly documented as disconnected and is not on the Flask startup path. No database, backup, or untracked project file was deleted.

## Intended architecture

- One Flask process, with Jinja as the primary interface and `/api/v1` as a session-authenticated API.
- One authoritative SQLite file selected by `APAAR_DB_PATH`, defaulting to `instance/apaar_demo.db`.
- Root website and API operate on the same `students` table and derive user, role, and institution from the server-side session and `users` table.
- Keep legacy website verification rows as source provenance and use `workflow_cases` as the canonical model after the tested additive migration.
- Synthetic demo data only. Local checks and demo statuses are not official government verification.

## Database plan

- Inspect schemas and metadata only before any migration; never print student rows.
- Preserve both existing SQLite files. Do not copy or drop data automatically.
- Use SQLite's online backup API before schema changes to an existing primary database.
- Keep migrations additive and idempotent; configure foreign keys and indexes; test using isolated temporary databases.
- Treat the root database as authoritative. The old API database stays untouched pending explicit data review/migration.

## Security plan

- Ignore caller-supplied identity headers; require a valid Flask session for API data routes.
- Enforce role and institution scope on page and API reads/writes.
- Keep parameterized SQL, password hashing, secure cookie defaults, security headers, request size bounds, and nonrevealing errors.
- Require CSRF tokens on browser/API state changes, throttle repeated login failures, bound session lifetime, ensure logout uses POST, validate redirects and inputs, and avoid trusting institution values from CSV/forms.
- Preserve a clear disclaimer: no APAAR/ABC/DigiLocker/government connection or official verification is implemented.
- Require CSRF tokens on browser/API state changes, throttle repeated login failures, and bound session lifetime; document the production limits of process-local controls.

## Implementation phases

1. Audit Git state, code entry points, dependency manifests, database metadata, tests, and docs; record this plan before implementation.
2. Run the existing test suite and identify interpreter/dependency blockers.
3. Repair and consolidate the Flask shared database/API behavior, security boundaries, and end-to-end UI workflows without changing the meaning of existing user data.
4. Update tests and documentation to match the actual canonical architecture and runnable commands.
5. Run relevant tests/build checks; launch the app on an isolated temporary database and exercise login, student CRUD, verification, CSV, duplicate review, API, audit, and tenant isolation.
6. Remove only source implementations proven unused after reference/config/test searches and successful replacement verification. Preserve prototype source and user data when dependencies or unique functionality remain uncertain.

## Implementation results (2026-10-22)

- Selected Flask/Jinja plus its Flask API based on persistent shared data, session authentication, and the working website workflows. React/Express has broader visual coverage but its screens use fixtures, in-memory state, mock identity, and no persistence or authorization. It remains preserved as inactive prototype source.
- Kept SQLite as the authoritative store based on `APAAR_DB_PATH`, the root README, and executable Flask code. Read-only metadata showed four rows in `apaar_demo.db` and one row in the differently shaped `apaar_backend.db`; no database rows were copied or changed.
- Added API student updates, tenant checks, CSRF, login throttling, soft archive, CSV preview/confirmation/history/idempotency, pagination, explainable duplicate signals, case review UI, audit hash verification, and migration backup verification.
- Removed the unused root Node manifest. Kept the nested prototype, legacy API database, and previous database snapshot.
- Assessed the nested prototype dependencies: web typecheck/build and API TypeScript build pass after compatibility/dependency fixes; API tests remain blocked before collection by unresolved `encodeurl`, and npm reports six vulnerabilities. The workspace remains preserved but disconnected from runtime.
- Repaired Python 3.11.9 and the stale `.venv`, installed declared requirements, ran **23 passing pytest tests**, and exercised the Flask server over HTTP on a new temporary database.
- At the end of the consolidation phase, the primary database had not yet been migrated. The 2026-10-22 stabilization phase below records the later backup, staging test, and additive upgrade.

## Tests and acceptance criteria

- Initial consolidation suite passed on Python 3.11.9 (`23 passed` on 2026-10-22); see the stabilization results below for the current 30-test suite.
- API tests prove unauthenticated requests fail, forged headers cannot select identity/tenant, and website/API see the same student records.
- Institution isolation holds for website and API routes; validation and duplicate workflows do not mutate records unexpectedly.
- CRUD, verification, CSV preview/confirmation, audit, Review queue, and health workflows complete in an app launched against a temporary database.
- Existing SQLite files remain intact; any schema change to the primary database has a verified pre-upgrade backup.
- README and scripts give accurate setup, test, launch, demo-account, and limitation instructions. No official external integration is claimed.

## Stabilization phase (2026-10-22)

- Confirmed the configured primary path without exposing credentials or row contents. Created a SQLite online backup and verified integrity plus a logical dump checksum match. Immediately before migration, the primary still matched that baseline.
- Added [the case mapping specification](CASE_MIGRATION_MAPPING.md) before implementation. It maps legacy website validation history into canonical `workflow_cases` as `legacy-web:<id>`, retains original result/status/source/findings/timestamp, leaves existing API UUIDs unchanged, and documents state mapping, rollback, audit references, and repeat behavior.
- Tested the additive schema and migration against a separate staging clone of the verified backup with synthetic test history. Original rows/columns, existing workflow UUID/audit reference, hash-chain validity, migration idempotency, and SQLite integrity all passed.
- Migrated the primary DB after staging verification. Startup created a second pre-upgrade backup whose integrity is `ok` and whose logical dump checksum matches the pre-migration baseline. Primary integrity is `ok`; existing student/user/legacy audit row counts are unchanged. The legacy API database was not touched.
- Replaced website-only history writes and API-only workflow operations with shared case creation/transition services, scoped timelines, one case model, and human reviewer checks. Added synthetic evidence metadata (no files), restricted institution-scoped account administration, active-account checks, and conflict-aware archive restoration.
- Added migration mapping/idempotency/rollback, evidence/reviewer, account, restore, production credential guard, and full end-to-end workflow tests. The consolidation suite first passed **30 tests**; final stabilization reached **31 passed** after read-only Review and audit-metadata regressions were covered. Fresh isolated Flask servers passed the recovery and synthetic HTTP rehearsals.
- Prototype disposition remains inactive/preserved. React typecheck/build and API TypeScript build pass; Express API test collection remains blocked by unresolved `encodeurl` in the installed dependency tree. npm reports six vulnerabilities; registry advisory details were unavailable. No forced audit fixes were applied.
- Final stabilization independently reran tests and backup/recovery checks. Duplicate scans now use an explicit CSRF-protected POST so Review and candidate-list GETs are read-only; audit metadata omits institutional student codes. The current state, isolated HTTP rehearsal, and backup fingerprint results are recorded in `CURRENT_STATE_AUDIT.md`.
