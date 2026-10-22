# UI regression checklist

Run against a fresh synthetic database. The current automated suite exercises the Jinja pages through Flask's test client; this checklist is for a real browser walkthrough before demonstrations.

## Desktop, tablet, and mobile

- [ ] Sign in and verify the dark navy navigation, visible page title, session user, and sign-out action.
- [ ] At 1280 px, 768 px, and 390 px viewport widths, confirm no page-level horizontal overflow. Tables may scroll inside their own table container.
- [ ] Keyboard-tab through navigation, primary actions, forms, filters, and timeline disclosure controls. Confirm the focus ring is visible.
- [ ] Enable reduced motion in the operating system/browser and confirm transitions do not animate materially.
- [ ] Confirm success, warning, and error messages remain distinguishable by text as well as color.

## Role-aware flows

- [ ] Institution administrator: create a verifier, import a source CSV, assign and reassign an active case, inspect the timeline and audit event.
- [ ] Operator: open source data, preview and confirm a synthetic dataset; confirm student edit actions work.
- [ ] Verifier: inspect records and resolve only an assigned case; confirm an unassigned reviewer cannot resolve an assigned case.
- [ ] Auditor: inspect student and audit records, export only permitted scoped reports, and confirm student edit/create controls are absent and POSTs are denied.

## Core pages

- [ ] Overview metrics and links reflect records/cases in the signed-in institution.
- [ ] Student search, course/semester/status filters, detail page, and pagination work.
- [ ] Import preview displays row validation and confirmation state; errors are actionable.
- [ ] Source dataset preview shows validation and version counts without full identifier values.
- [ ] Review queue filters assigned/unassigned work; assignment and case transitions show in the timeline.
- [ ] Submit a stale case form from a second session after the case changes; confirm it shows a conflict and does not add a timeline event.
- [ ] Compare a student with a confirmed source dataset, inspect field findings and provenance digests, import a later version, and confirm the prior result is labelled stale.
- [ ] Audit page filters return scoped history and show hash-chain integrity status.
- [ ] Confirm no page labels a mock or institution-source comparison as official APAAR/ABC/DigiLocker verification.
