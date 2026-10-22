# Flask API status

The versioned Flask API is registered in the canonical Flask application at `/api/v1`. It uses the same SQLite path and `students` table as the Jinja website. API identity is read from the authenticated Flask session and the corresponding user row; `X-User-Id`, `X-Institution-Id`, and `X-User-Role` do not authorize requests.

## Implemented endpoints

- Health and institution-scoped student list/get/create/update.
- CSV dry-run that does not write student records.
- Duplicate candidate scan and human decision endpoints. Name similarity is configurable with `DUPLICATE_NAME_SIMILARITY`; decisions record reviewer, time, and reason and never merge automatically.
- Verification cases share `workflow_cases`, a common service and state machine across the website and API. Endpoints provide create/list/transitions, scoped timeline, and synthetic evidence metadata/review. Website legacy validation rows migrate once to IDs `legacy-web:<legacy integer ID>`; original fields/status/timestamp remain preserved. See `CASE_MIGRATION_MAPPING.md`.
- Institution-admin account creation, activation/deactivation, and assignment of operator/verifier/auditor roles are available through `/admin/users`.
- Archive restoration preserves internal IDs and history; conflicts require an explicit replacement institutional ID.
- Institution-scoped audit list and `/audit/integrity` hash-chain verification.
- Session CSRF validation applies to API writes; JSON callers send `X-CSRF-Token`.

## Remaining work

There is no API token-provider flow, system-admin or cross-institution account management, evidence file upload, case assignment, external identity integration, or general versioned migration framework beyond tested additive startup migrations. Institution administrators manage users only in their own institution and cannot grant administrator roles. Evidence is metadata only and labelled synthetic. Login throttling is process local. Do not deploy this prototype for real student data.

No APAAR ID issuance, live APAAR/ABC/DigiLocker integration, automatic identity merge, or fraud classification is implemented.
