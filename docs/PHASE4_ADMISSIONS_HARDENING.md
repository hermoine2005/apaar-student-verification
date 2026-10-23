# Phase 4 — Admissions workflow hardening

## Implemented

- Intake capacity checks and enrolment creation now run under a SQLite `BEGIN IMMEDIATE` transaction so concurrent submissions cannot both consume the final seat.
- Enrolment identifiers are checked case-insensitively after trimming whitespace and are scoped to the current institution. The check and insert run inside the same write transaction.
- Submission version allocation is serialized and the live enrolment status is rechecked after acquiring the write lock, preventing stale concurrent requests from creating extra submission versions.
- Review decisions update only a still-pending latest submission. A competing or repeated decision that no longer matches the pending state is rejected instead of overwriting the first decision.
- Rejection and return-for-correction actions require a reason; the reason is stored with the review decision.
- Added regression tests for normalized duplicate enrolment IDs and mandatory review reasons.

## Validation

Python syntax compilation passed for `app.py`, `backend/migrations.py`, and `tests/test_admissions_workflow.py`.

The full pytest suite could not be run in this build environment because Flask is not installed and package-index access is unavailable. These tests must be run in the project's configured virtual environment before demo or deployment.

## Remaining boundary

This is application-level concurrency protection for SQLite, not a substitute for a production database and operational deployment controls. There is no official APAAR/ABC/DigiLocker integration in this phase. Use synthetic data for demonstrations.


## Follow-up correction in Phase 5

A deeper schema/workflow review found that the `return` action wrote `returned_for_correction` into `enrolments.status`, while the original table CHECK constraint did not permit that value. Phase 5 adds a backup-first idempotent migration and a regression test for the mismatch. The full Flask integration suite remains unverified in the build environment.
