# Current State Audit

Audit date: 2026-10-22. The canonical SQLite database was migrated after a verified SQLite online backup and a successful migration run against a separate staging clone. The legacy API database was not modified.

## Architecture decision

The canonical application is Flask/Jinja in `app.py`, with the versioned Flask API registered in the same process under `/api/v1`. Website and API student reads/writes use the `students` table selected by `APAAR_DB_PATH`, defaulting to `instance/apaar_demo.db`. Server-side user rows and signed Flask sessions provide identity; caller-supplied `X-User-*` headers are ignored.

The React/Vite/Express workspace in `apaar-platform-upgrade/` has a polished and broad screen design: overview, students, verification queue, duplicate review, imports, audit, and reports. Inspection of `apps/web/src/App.tsx` and `apps/api/src/index.ts` found hardcoded student/case/audit fixtures, browser-local state mutations, mock reviewer identity, an in-memory Express `Map`, no authentication, and no persistent database. Its write paths do not call Flask. Its package manifests/lockfile provide a real TypeScript/Vite/Express test/build setup, but this is a disconnected prototype, not a more complete working application. It is preserved because the source is untracked user work and its screen design may be useful; it is not part of the canonical startup path.

The retained Flask site has persistent records and the most complete real workflows, including session login, student create/view/edit, local validation, CSV export, and audit. The Flask API adds shared student CRUD, dry-run, duplicate review, verification cases, and hash-linked events. The main UI now includes duplicate and case review and displays workflow audit events. For these reasons Flask/Jinja is the single primary application, with its API integrated in process.

## Database evidence and preservation

SQLite is the configured and implemented database: `app.py` uses `sqlite3`, defaults to `instance/apaar_demo.db`, and there is no executable PostgreSQL/Prisma configuration. PostgreSQL in `README_dev.md` and the React prototype docs is future proposal material, not an implemented requirement.

A SQLite metadata inspection found:

- `instance/apaar_demo.db`: 4 student rows, one user, and the legacy website verification/audit tables; its API workflow tables are in the same file.
- `instance/apaar_backend.db`: one legacy API student row in a different schema and one hash-linked event.
- `instance/apaar_demo.pre-upgrade-20261022T110831Z.db`: a prior pre-upgrade snapshot containing the original four website student rows and legacy schema.

No student values or credentials were printed. The main database is canonical because the Flask app and README configure it as the working application database. The old API file remains intact as an offline recovery source; its distinct field mapping (including a date-of-birth column absent from the main schema) requires review before any migration.

On startup, the app detects missing additive columns/tables and snapshots an existing SQLite file through `Connection.backup()` before schema changes. A consistent backup was created before this stabilization work, then the startup-generated pre-upgrade backup was checked for integrity and its logical dump checksum was compared with the untouched pre-migration baseline. Both matched. The primary database now has the additive archive, user-active, case, evidence, and import schema; its integrity is `ok`, with the original four student rows, user row, and audit-log rows preserved. No rows were copied from or written to `apaar_backend.db`.

## Implemented workflows

- Flask session login/logout with Werkzeug password hashing, eight-hour permanent sessions, HTTP-only/SameSite cookies, CSRF tokens on state-changing requests, 2 MB request limits, and process-local login throttling.
- Institution-scoped role checks for website and API routes. API actors are loaded from the session username and `users` table; identity/role/tenant headers do not authorize requests.
- Student search, status filters, 50-row pagination, create, view, edit, local validation, soft archive, and conflict-aware restoration. Restoration retains the student ID/history and requires a replacement institutional ID if uniqueness conflicts.
- Shared student create/list/update through the website and API with common IDs; API updates enforce tenant scope and unique-code conflicts.
- CSV preview in persistent import tables, row validation and warnings, exact-file hash de-duplication, row-error CSV, explicit confirmation, and one transaction for all valid rows. The signed-in account supplies institution context.
- Duplicate candidates use normalized exact/thresholded name similarity plus email/course signals. Explanations, reviewer, timestamp, decision, and reason are stored. Review and candidate-list GETs are read-only; authorized operators/admins explicitly run a CSRF-protected POST scan. No automatic merge occurs.
- `workflow_cases` is the canonical verification case table used by the website and API. Existing API workflow UUIDs remain unchanged. Legacy website local-validation rows are copied once to IDs `legacy-web:<integer-id>`; original integer IDs, outcome text, findings, source, and timestamps remain in the source table and canonical row. `Needs review`/`Pending` map to `open`; successful or unknown outcomes map to `recorded`, never to reviewer approval. The repeatable migration aborts on invalid student/institution references and runs in a savepoint.
- Case creation and transitions share one service, transition rules, institution checks, an event timeline, and hash-linked audit events. Resolving/closing requires an 8–1000 character reason and a reviewer other than the case creator.
- Evidence metadata records type, source, authenticated uploader/time, review state, reviewer/time, description, and optional validated SHA-256 checksum. It is metadata only; no file is uploaded or represented as an official document. A different authorized reviewer must decide on it.
- Institution administrators can create/deactivate accounts in their own institution and assign operator/verifier/auditor roles. Passwords are Werkzeug hashes, account changes are hash-audited, inactive accounts are blocked, and administrator promotion/cross-institution membership management is not exposed.
- Legacy audit records and workflow audit events appear on the audit page. Hash-linked workflow events can be checked through `/api/v1/audit/integrity`; tampering is tested and detected. This local hash chain is not tamper-proof against a database administrator.
- CSV export is institution scoped, role protected, audited, and neutralizes formula-leading cell values.

## Test and runtime evidence

Python 3.11.9 was installed after diagnosing that the stale `.venv` referenced a missing Microsoft Store Python path. The workspace `.venv` was recreated and dependencies from `requirements.txt` were installed. `python-dotenv` is now declared so `.env` is actually loaded.

`python -m pytest -q`: **31 passed** after final stabilization fixes. The suite covers shared website/API IDs and updates, tenant isolation, forged headers, CSRF including duplicate scanning, throttling, archive/restore conflicts, account administration, production first-admin safeguards, legacy case mapping/idempotency/rollback, evidence decisions, reviewer separation, CSV preview/commit/replay/conflict rollback, pagination, duplicate signals, workflow/evidence foreign keys, backup-before-migration, audit metadata minimization, and audit-chain tampering. The single end-to-end synthetic demo workflow passes.

The Flask server was launched against a fresh temporary SQLite file at `127.0.0.1:5093`. Real HTTP checks completed health, login, API student listing, Review queue rendering, and the restricted user-management page. The temporary database is separate from `instance/`. A Flask-client end-to-end test additionally exercised create/edit/API read, CSV validation and import, human duplicate decision, case/evidence review by a second account, audit integrity, CSV export, and cross-institution denial.

The nested prototype was dependency-installed and its compatibility issues in three `String.replaceAll` calls were corrected. Web `typecheck` and production Vite build pass (Vite reports a 604 kB minified JS chunk). API TypeScript build passes. API tests still fail before collection because `apps/api/node_modules/finalhandler` cannot resolve its declared dependency `encodeurl`, even after clean install and lockfile updates; no prototype API tests ran. npm install reports six vulnerabilities (3 moderate, 1 high, 2 critical); `npm audit` could not reach the registry advisory endpoint, so the packages/advisories are not verified.

## Consolidation and cleanup decision

- Removed the root `package.json` after checking its `workspaces` target directories were empty, that it had no root lockfile or runtime references, and that its only test command was a placeholder that exited with failure. The nested prototype keeps its own package manifests and lockfile.
- Kept `apaar-platform-upgrade/`, its manifests, and its docs as inactive prototype source rather than deleting untracked user work or losing useful screen design before feature migration.
- Fixed the prototype web's ES2021 `replaceAll` use for its configured TypeScript target and added the missing `formidable`/`depd` API dependencies to its manifest/lockfile while assessing install health. The API test runner remains blocked by the missing `encodeurl` package in the installed Express dependency tree; the prototype is still inactive.
- Kept the separate legacy API SQLite file and prior database backup untouched.
- Added a historical-proposal notice to `README_dev.md`; the root README is the runnable setup guide.

## Remaining limitations

- No system administrator role or cross-institution user/membership administration. An institution administrator manages accounts only inside their own institution and cannot promote any account to administrator.
- Login throttling is in-process memory and resets on restart; production deployments need shared rate limiting and an appropriate WSGI server.
- Browser sessions and the API use the same CSRF header/token flow. External API consumers must obtain and send `X-CSRF-Token` after session authentication.
- Case assignment, file uploads, and physical evidence retention are not implemented; evidence metadata is synthetic and non-file based.
- No automated archived-record purge or retention schedule is configured; restoration is available to institution administrators.
- Duplicate detection has no DOB or other authoritative identity field. Its score is only a review signal, not identity proof.
- The import workflow does not support configurable column mapping or import retention/deletion, and failed post-preview conflicts stay in preview state.
- No official APAAR, ABC, DigiLocker, or other government integration exists. Use synthetic records only; this is not production-ready.

## Final stabilization verification (2026-10-22)

- The Flask suite passed 30 tests before stabilization edits and **31 tests** afterward. Python AST syntax parsing and `git diff --check` passed.
- All SQLite files and available snapshots opened successfully and returned `PRAGMA integrity_check = ok`. Row fingerprints for the primary database match the verified pre-trigger snapshot; the primary’s current schema has the additional tenant-scope triggers. The legacy API database stayed separate.
- A separate recovery copy launched on a local port and passed login/logout, student listing, Review, account administration, and website/API shared create/update checks. A brand-new synthetic database passed real HTTP checks for student CRUD, CSV preview/confirmation, duplicate human decision, verification workflow with a second reviewer, evidence metadata, audit-chain integrity/tamper detection, safe CSV export, cross-institution denial, account deactivation, and archive/restore conflicts. After the final read-only Review/CSRF scan and audit-metadata fixes, another isolated HTTP check verified those changed paths; the full 31-test suite passed against the final code.
- API student creation and archive audit entries now omit the institutional student code. SQLite sidecar/temp ignore patterns were added. The React/Express prototype was not modified and remains preserved/inactive.
- The real primary and legacy database logical fingerprints matched their initial values after all rehearsals. No migration was run against either file during final stabilization.
