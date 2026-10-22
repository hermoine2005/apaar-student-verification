# Implementation plan — SIH26263 platform overhaul

## Baseline and constraints

- Canonical runtime: root Flask/Jinja app, shared `/api/v1` blueprint, SQLite selected by `APAAR_DB_PATH`.
- Test setup redirects to `.pytest_cache/apaar-test.db`; per-feature fixtures use temporary databases. Protected demo/backend DB files are out of scope.
- `apaar-platform-upgrade/` is disconnected, untracked prototype content and will remain untouched.
- Baseline on 2026-10-23: `85 passed, 1 failed`; source reference CSV parsing accepts an unsupported `apaar_id` column, contrary to the existing regression test and privacy boundary.

## Delivery phases

1. **Close data exposure regression** — reject identifier and unsupported fields in institution source CSV; retain only the comparison schema. Acceptance: parser/import tests prove rejection and no sensitive source field enters preview persistence.
2. **Authorization and case control** — preserve institution-scoped existing roles; verify admin/operator/verifier/auditor server checks, assignment scope, reviewer separation, and read-only restrictions. Acceptance: tests cover allowed and denied mutations, cross-tenant targets, and CSRF.
3. **Reconciliation/work queue coherence** — extend existing source-version summaries, comparison history, case assignment, workload counts, and audit provenance. Acceptance: outcomes remain source-version scoped, student rows are not mutated, and unresolved work links to an authorized queue action.
4. **Visual consistency and responsive use** — centralize existing CSS tokens and strengthen the shared shell, navigation, forms, tables, focus states, and mobile overflow behavior without replacing Jinja or adding dependencies. Acceptance: templates render in test client; documented manual viewport checklist covers dashboard, students, import, review, and audit screens.
5. **Operational metrics, tests, and handoff** — add only database-derived metrics supported by existing records; run focused tests then one final full suite; document implemented and blocked requirements. Acceptance: isolated DB checks pass, migration remains additive, and docs state no official provider integration.

## Dependencies and risks

- Startup currently initializes/additively migrates SQLite schemas. Any schema extension must be tested on a fresh temporary DB and trigger the existing pre-upgrade backup check for existing databases.
- The account model is institution-scoped and has no institution registry or platform administrator. Do not invent cross-tenant administration without a model and policy.
- Source comparisons are single-student operations and are distinct from official provider verification. A batch reconciliation run model, stale-result impact analysis, authoritative provider, encryption at rest, and live browser automation remain separate concerns unless safely delivered end to end.
- Manual visual checks are required if no browser automation is available. No external service, real credentials, production student data, or protected database is used.

## Work completed and validation

- Source-reference CSVs now reject `apaar_id` and `notes`; importing these fields is not needed for institution comparison and could expose unnecessary identity data.
- Data-entry operators can preview and confirm institution source datasets through the same existing service and routes as institution administrators.
- The overview now links to source import and displays institution-scoped assigned/unassigned active-case counts. Review queue filters and CSV export honor assignment selection.
- Student write controls are hidden for auditors while server-side authorization continues to reject their direct create request. `ROLE_PERMISSION_MATRIX.md` documents the current route policy; role-matrix tests exercise read, write, export, tenant IDOR, and privilege-escalation boundaries.
- Case transitions accept an expected update timestamp and compare-and-update both status and version. Stale browser/API edits return a conflict and leave state and audit history unchanged.
- Institution source comparisons persist run status, dataset version and content digest, comparison ruleset version, field outcomes, outcome counts, result digest, and a student update snapshot. The student page and API flag results as stale after a dataset version, student record, or ruleset change. Existing rows are upgraded additively.
- Shared page styling adds a restrained navy/teal palette, focus-visible outlines, reduced-motion handling, and narrow-screen/table overflow rules. Manual browser viewport checks remain outstanding.
- Earlier focused tests: 25 passed; earlier full suite: 88 passed in 92.42 seconds, exit code 0. Current focused role/case/provenance/migration tests: 6 passed; full suite: 90 passed in 97.18 seconds, exit code 0. See README for the exact full-suite command.
- Synthetic source-data timing harness passed on a temporary SQLite database at 1,000, 4,000, and 8,000 rows; measurements are in `SOURCE_DATASET_BENCHMARK.md`.
- `git diff --check` passed. Protected database files and the disconnected prototype show no changes from this work.

This delivery is a targeted reliability and usability increment, not completion of every overhaul objective. There is still no platform administrator/institution registry, secure invitation/password-reset flow, batch reconciliation run/provenance model, stale-result impact view, official provider, at-rest encryption, or multi-worker deployment support. The implementation remains an institution-scoped local prototype; see README for workflow and deployment limitations.
