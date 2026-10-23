# Phase 5 — Purpose-limited data-use authorization register

## Implemented

- Institution-scoped authorization records linked to a student and limited to an enumerated purpose and data-category set.
- Captures asserted authority basis, optional expiry, internal evidence reference, recorder, timestamp, and withdrawal metadata. No evidence files or raw identity documents are uploaded by this feature.
- Authorization creation is role-gated, CSRF-protected, tenant-scoped, validated, and serialized while checking for an existing effective authorization.
- Withdrawal is one-way and audited; prior submission records retain their authorization reference for historical traceability.
- Admissions submission now requires a current authorization for `admissions_submission` covering identity, academic record, and admissions record. The selected authorization ID is stored on the submission version.
- Fixed the Phase 4 state mismatch: `returned_for_correction` was written by the workflow but excluded by the enrolment table CHECK constraint. An idempotent, backup-first migration now expands the allowed state and preserves submission rows and foreign-key relationships.
- Added regression tests for authorization-gated submission and the admissions schema migration.

## Important limits

This is an internal authorization register, not a legal determination, consent-management certification, or evidence that consent was validly obtained. Institutions must determine the lawful basis and required guardian/subject process. The app does not verify uploaded evidence because this feature deliberately stores references only. Existing historical submissions are not retroactively invalidated.

## Validation status

Python syntax compilation passes. Standalone SQLite migration tests are included, but the full Flask test suite could not be run in the current build environment because Flask/Werkzeug are not installed and package index access is unavailable. Do not mark this phase end-to-end verified until tests pass in the project environment.
