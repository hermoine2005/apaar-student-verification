# Engineering audit — 2026-10-23

## Scope

This audit inspected the consolidated Phase 5 source package, startup/configuration path, SQLite connection lifecycle, migration code, admissions authorization flow, existing test layout, and package hygiene. It is a source-level audit plus isolated SQLite smoke checks, not a complete application acceptance test.

## Defects corrected in this build

1. **Secret placeholder acceptance.** `.env.example` used `replace-with-a-random-secret-key`, but the prior runtime check only recognized two exact placeholders. The runtime now rejects any `replace-with-` secret as a real key, uses a random development-only fallback, and refuses missing/placeholder keys when `APP_ENV=production` or `FLASK_ENV=production`.
2. **SQLite connection lifetime.** Python's standard SQLite connection context manager commits or rolls back but does not close the connection. The app's common `with connect_db()` pattern now uses a connection subclass that closes at context exit. Explicitly managed connections remain manually closed by their existing `finally` blocks. A 15-second SQLite busy timeout is configured.
3. **Benchmark script warning.** The Windows command in the benchmark script's docstring is now in a raw docstring, removing the invalid-escape warning during compilation.
4. **Validation claims.** README and status ledger now state that the earlier 90-test result is historical and not reproduced by this audit. No claim of a passing current full suite is made.

## Checks executed in this packaging environment

- `python -m py_compile app.py backend/*.py bootstrap_admin.py tests/*.py`: **passed**.
- Isolated student-ID migration smoke test: **passed**. Verified preservation of two legacy rows and a related foreign-key record, same identifier allowed across institutions after migration, case/trim-normalized duplicate rejected within an institution, FK check clean, and second migration run a no-op.
- Isolated secret resolver / connection lifecycle smoke test: **passed**. Placeholder rejected in production mode, development fallback is random-length, and a context-managed SQLite connection is closed after exit.
- ZIP integrity: checked when producing the release package.
- `python -m pytest -q`: **blocked at collection** because Flask and Werkzeug are not installed in this environment. Installing requirements was attempted but the package index could not be resolved (network/DNS unavailable). The full application test suite therefore remains unverified.

## Not verified / remaining engineering work

- Full pytest suite on the target Python/Flask environment and browser-level end-to-end flows.
- Concurrency stress tests for capacity and workflow state transitions.
- Tenant-isolation tests for every route and API path after all migrations.
- Restore drill from a real, representative database backup.
- Independent security review, rate limiting across multiple workers, production monitoring, deployment/TLS/cookie configuration, and operational incident response.
- Official APAAR/ABC/DigiLocker integration. No authorized provider adapter or credentials are included; local rules and mock outcomes are non-authoritative.
- Cross-institution duplicate reconciliation, platform-wide institution registry, richer intake/admissions lifecycle, reporting/pagination gaps, and retention/deletion policy remain planned or partial as described in `ENGINEERING_STATUS.md` and `CURRENT_STATE_AUDIT.md`.

## Safe local setup

1. Install Python 3.11+.
2. Create and activate a virtual environment.
3. Install `requirements.txt`.
4. Copy `.env.example` to `.env` and replace both secret placeholders. For a local demo use `APP_ENV=development`; for production secret validation set `APP_ENV=production` and configure HTTPS plus `COOKIE_SECURE=1`.
5. Use synthetic data and a disposable database first. Back up any existing database before startup because startup may run migrations.
6. Run `python -m pytest -q`. Do not treat the project as verified until the suite passes in the configured environment.
7. Start with `python app.py` for local demonstration only. Do not expose Flask's development server to the public internet.
