# Phase 1 security and correctness changes

This log records changes made to the supplied working copy. It is not a claim that changes have been pushed to GitHub.

## Applied

1. **API student creation:** the shared API now persists the submitted `apaar_id` field, which it previously validated but omitted from the SQL insert.
2. **Regression test:** added a test asserting the identifier is persisted but is not exposed in the student-list API, student detail page, or CSV export.
3. **Administrator bootstrap:** removed the hard-coded personal username, email, and password from `bootstrap_admin.py`. It now prompts for credentials (password entry is hidden), requires a password of at least 16 characters, creates a timestamped database backup, and refuses to reset a matching account unless `--update-existing` is explicitly supplied.
4. **First administrator setup:** removed the application's implicit fallback password. A new database now requires `DEMO_ADMIN_PASSWORD` to be set in `.env`; the example placeholder is rejected.
5. **Environment setup:** added `.env.example` with placeholders, and updated `README.md` and `run.cmd` to instruct the developer to configure private credentials rather than print a known demo password.
6. **Login page:** removed the hard-coded demo username/password banner.

## Validation

- `python -m py_compile app.py backend/routes.py tests/test_backend_foundation.py bootstrap_admin.py`: passed.
- `python -m pytest -q`: could not collect tests because Flask and Werkzeug are not installed in this execution environment.
- `python -m pip install -r requirements.txt`: could not install dependencies because package-index DNS/network access is unavailable.
- The full test suite therefore remains **unverified**. Run it locally after installing `requirements.txt`.

## Security follow-up still required

- Treat the credential formerly embedded in `bootstrap_admin.py` as compromised: rotate it immediately anywhere it was used. Removing it from the current file does not remove it from existing Git history. History cleanup should be coordinated with repository collaborators because rewriting history affects all clones.
- Check repository history and any shared copies for additional credentials before deployment.
- Institution-scoped uniqueness still needs a separately tested SQLite schema migration. The current global unique constraint cannot safely be removed with a one-line change because related foreign keys and triggers must be preserved.
- No official APAAR/ABC/DigiLocker provider, institution registry, admissions/intake monitoring, or central cross-institution reconciliation has been added in this phase.

## Phase 2 — institution-scoped student identifiers

- Added an idempotent SQLite migration that replaces the legacy global unique constraint on `institution_student_id` with a case-insensitive unique index over `(institution, institution_student_id)`.
- The migration creates and integrity-checks a timestamped database backup before rebuilding the `students` table, preserves IDs and existing student fields, and checks foreign-key integrity after the rebuild.
- If the database already contains case-insensitive duplicate identifiers within one institution, startup stops with a clear error before changing the schema. Resolve those records and restart; do not delete records just to force migration.
- Updated form-level duplicate checks, archive restoration, and CSV import preview/commit checks to scope IDs to the current institution.
- Added focused migration tests for cross-institution reuse, same-institution conflicts, backup creation, idempotency, and refusal to migrate ambiguous data.

Validation note: Python syntax compilation passes. Full pytest execution remains unverified in this environment because Flask/Werkzeug dependencies are not installed and package-index network access was unavailable. Run `python -m pytest -q` in the project's configured virtual environment before using this build with real data.
