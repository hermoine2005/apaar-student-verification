# Verification Case Consolidation Mapping

## Source tables

`verification_cases` is the legacy website history of deterministic local validation runs. It records an integer ID, student ID, outcome status, summary, findings, source, and creation time. It does not record a reviewer or case transitions. These rows are historical evidence of a demo check, not proof of official identity verification.

`workflow_cases` is the API review workflow. It records a UUID case ID, institution, student, case type, status, priority, reason, optional resolution note, creator, and created/updated times. Hash-linked events refer to the original UUID in `audit_events`.

## Canonical model

`workflow_cases` remains the canonical table because it already backs API case operations and can represent active workflow. Additive columns preserve legacy outcome/source details and a `(legacy_source, legacy_id)` mapping. Existing workflow UUIDs remain unchanged so their audit references remain valid. A website history row is assigned canonical ID `legacy-web:<integer-id>` and its original integer is preserved in `legacy_id`; this deterministic mapping is unique and repeatable.

Canonical case states are `open`, `in_review`, `waiting_for_evidence`, `escalated`, `resolved`, `closed`, and `recorded`. Existing website local-check outcomes map as follows:

| Legacy website outcome | Canonical state | Preserved value |
| --- | --- | --- |
| `Needs review`, `Pending` | `open` | Original text in `legacy_status`; summary, findings, source, timestamp retained |
| `Demo-validated`, `Verified`, `Approved` | `recorded` | Original text in `legacy_status`; not represented as reviewer approval |
| Any other value | `recorded` | Original text in `legacy_status`; no inferred decision |

The canonical `case_type` is `legacy_local_validation`. `reason` is copied from the legacy summary, `findings` and `source` remain in dedicated columns, and the original timestamp is retained as `created_at` and `updated_at`. Legacy rows receive a `case.migrated` timeline event with actor `migration`; this is provenance and does not claim a human review. Their integer IDs are not changed or deleted from the legacy source table.

No current API workflow row is copied into a second row: it already is in the canonical table. A repeat run skips any website source ID already present via the unique mapping. The migration runs in one transaction and aborts on missing or cross-institution student references; it never silently drops a legacy row. The legacy source table remains read-only provenance after cutover. Existing `audit_logs` and `audit_events` are preserved; API workflow IDs remain unchanged.

## Safe rollout and tests

Take a SQLite online backup and verify integrity/table counts before schema changes. First test the additive schema and one-time import on a separate copy, including legacy case rows, linked students, IDs, timestamp/state mappings, audit references, a forced-failure rollback, and repeat execution. Do not migrate the primary database unless that copy test passes. The old API-only database is not part of this mapping and remains untouched.
