# Engineering status ledger

This ledger deliberately distinguishes implementation from runtime verification. A passing syntax check or SQLite smoke test is not equivalent to a passing Flask integration suite.

## Current consolidated build

| Area | Implementation state | Evidence in this build | Remaining validation / risk |
|---|---|---|---|
| Phase 1 — security and correctness fixes | Implemented in source | Bootstrap password is no longer hard-coded in production flow; API student creation persists APAAR ID; private `.env.example` added; syntax compilation | Full authentication, bootstrap, import/export, and API tests must run in the project's Python environment. Rotate any credential that appeared in earlier source/history. |
| Phase 2 — institution-scoped student IDs | Implemented in source | Backup-first SQLite migration and prior smoke-test coverage; scoped case/trim-normalized unique index | Run `tests/test_migrations.py` and the full suite on a copy of the real project database before deployment. |
| Phase 3 — admissions and intake workflow | Implemented in source | Programme, intake, enrolment, versioned submission and review routes/templates; tests authored | Flask route tests not run in this build environment. Capacity and tenant isolation need integration tests on the target environment. |
| Phase 4 — workflow hardening | Implemented, with a defect found and corrected in Phase 5 | Write-locks around capacity/version/review mutations; required reject/return reason; migration smoke test | Full concurrent-request integration test is not run. SQLite serializes writers but this is not a substitute for production operational controls. |
| Phase 5 — data-use authorization register | Implemented; partially verified | Schema extraction and SQLite FK smoke test passed; migration smoke test passed; Python syntax compilation passed; regression tests added | Flask/Werkzeug unavailable here, so route/template tests and the full suite remain unverified. No legal determination is made by the register. |
| Official APAAR/ABC/DigiLocker integration | Not implemented | UI and documentation explicitly disclaim external authoritative verification | Requires authorized provider access, approved API contracts, credentials, privacy review, and provider contract tests. |
| Production deployment hardening | Not complete | Basic secret and session protections exist | Requires deployment configuration review, secure cookies/TLS, email delivery setup, operational backups/restore drill, monitoring, rate limiting, and independent security review. |

## Phase 5 design notes

- The register records an asserted authority basis, purpose, data categories, expiry, an internal evidence reference, recorder, and withdrawal history.
- It does not store consent-document uploads or prove that a valid consent/guardian process occurred.
- An admissions submission must reference a current, unexpired authorization covering `identity`, `academic_record`, and `admissions_record`.
- Withdrawal blocks future submissions that rely on that record; historic submission records remain for auditability. Retention/deletion policy needs institution/legal review.
- `returned_for_correction` was previously written by the workflow but excluded by the `enrolments.status` CHECK constraint. The migration now backs up the database, rebuilds the table, validates row counts/integrity/foreign keys, and is idempotent.

## Validation performed for this package

- `python -m py_compile app.py backend/migrations.py tests/test_admissions_workflow.py tests/test_migrations.py`: passed.
- SQLite execution of the active `init_db()` schema string with foreign keys enabled: passed; the new authorization foreign key and `returned_for_correction` state were exercised.
- Standalone legacy admissions migration smoke test: passed; existing enrolment/submission rows remained, `returned_for_correction` was accepted, integrity and foreign-key checks passed, and rerun was a no-op.
- `python -m pytest -q tests/test_migrations.py`: blocked during collection because importing the `backend` package requires Flask, which is unavailable in this environment.
- Full pytest suite, browser testing, accessibility review, concurrency stress test, production deployment, and official-provider integration: not run.

## Required verification before a demo or deployment

From the project root, activate the intended virtual environment and run:

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
```

Run against a disposable test database first. Before using an existing database, make a separate copy and confirm the startup-generated pre-upgrade backup is present. Do not use real student data for the demonstration until the remaining privacy, security, and deployment reviews are complete.


## Source audit findings and corrections (2026-10-23)

The source audit found two additional operational issues and corrected them in this build:

- `.env.example` used a `replace-with-...` secret placeholder that the previous app check did not recognize. The application now rejects any `replace-with-` value as a real secret, refuses missing/placeholder secrets when `APP_ENV=production` or `FLASK_ENV=production`, and generates a random development-only fallback otherwise.
- Python's SQLite connection context manager commits/rolls back but does not close the connection. `connect_db()` now uses a connection subclass that closes on context exit, and sets an explicit busy timeout. Routes that manually manage a connection remain responsible for closing it in their existing `finally` blocks.

Regression tests were added for both behaviors. These tests compile, but could not be executed in this packaging environment because Flask and Werkzeug are not installed and the package index is unreachable. The test count stated in older README text is historical and was not reproduced during this audit; do not treat it as a current test result.
