# Phase 3 — Admissions and intake workflow

## Added

- Institution-scoped programme catalogue with unique programme codes per institution.
- Intake allocations by programme and year, with capacity and draft/open/closed status.
- Enrolment records that link an existing, active student to an open intake.
- Capacity checks performed in the server-side transaction before creating an enrolment.
- Submission version history with submit, approve, reject, and return-for-correction decisions.
- Role gates: institution administrators/operators create records and submit; institution administrators/verifiers review submissions; auditors can read.
- Institution scoping on all admissions queries and mutations.
- Audit log entries for programme, intake, enrolment, submission, and review decisions.
- Admissions workspace and enrolment detail pages.
- Tests for the primary workflow and intake capacity enforcement.

## Data model

`programmes` → `intake_allocations` → `enrolments` → `enrolment_submissions`.
Enrolments remain distinct from student identity records. Each submission is versioned; review decisions update the current enrolment state while preserving the submission history.

## Prototype limitations

- The workflow is local to the configured institution and does not call an official APAAR, ABC, DigiLocker, or government API.
- No payment, merit ranking, seat reservation expiry, document upload, e-signature, or external admissions-system integration is implemented.
- A reviewer decision is a workflow state, not proof of official identity or eligibility.
- The current UI lists at most 500 active students and 100 recent enrolments; production use should add server-side search/pagination.

## Validation

Python syntax compilation passed. The focused pytest suite could not be collected in the build environment because Flask is not installed and package-index network access is unavailable. Run the full suite in the project virtual environment before demonstration.
