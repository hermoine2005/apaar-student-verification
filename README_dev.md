# APAAR Student Data Management & Verification Platform

**SIH 2026 | Problem Statement: SIH26263 | Software Category**

> A privacy-conscious, interoperable platform for managing student academic records, validating data quality, detecting inconsistencies, and supporting authorized academic record verification.

---

## 1. Project Overview

### 1.1 Purpose

The APAAR Student Data Management and Verification Platform is a proposed web application for streamlining institutional student record management and academic verification workflows.

APAAR (Automated Permanent Academic Account Registry) is part of India's student academic identity ecosystem and is linked with the Academic Bank of Credits (ABC) and DigiLocker.

The proposed application will provide an institutional interface for managing student records, checking data consistency, identifying duplicate candidates, documenting verification decisions, and integrating with authorized external academic record services when access is available.

### 1.2 Problem Statement

Academic records may be distributed across institutional information systems, spreadsheets, admission databases, examination systems, and digital document repositories.

Manual record reconciliation can introduce delays, duplicate entries, inconsistent student details, limited traceability, and unnecessary administrative effort.

Institutions require a structured way to:

- Maintain consistent student and academic records.
- Associate institutional student profiles with APAAR identifiers where appropriate and authorized.
- Identify missing, inconsistent, or potentially duplicated information.
- Support documented review and correction workflows.
- Exchange academic data through authorized interfaces.
- Maintain access controls, provenance, and auditable verification history.
- Protect student information throughout its lifecycle.

### 1.3 Proposed Solution

Build a modular web platform combining student record management, deterministic validation, duplicate candidate detection, controlled verification workflows, institutional analytics, and a provider-independent integration layer.

The application must distinguish local data validation from authoritative external verification.

**The initial release will use synthetic demonstration data. It will not claim to create APAAR IDs, access private government databases, or officially verify academic credentials without an approved integration and valid source response.**

### 1.4 Project Goals

1. Reduce repetitive manual academic record checks.
2. Improve institutional data consistency.
3. Make discrepancies explainable and actionable.
4. Provide traceable verification and correction workflows.
5. Minimize unnecessary access to personal information.
6. Establish a maintainable architecture for future authorized integrations.
7. Demonstrate a complete, deployable prototype within free-tier constraints.

---

## 2. Scope and Product Boundaries

### In scope

- Student profile and academic record management.
- Institutional record import and export.
- Configurable validation rules.
- Duplicate candidate identification.
- Verification case management.
- Source provenance and audit history.
- Consent and access-purpose records where applicable.
- Role-based and institution-scoped authorization.
- Reports, dashboards, and operational analytics.
- Mock external provider integration.
- Integration readiness for authorized APAAR/ABC/DigiLocker APIs.
- Testing, documentation, and public demonstration deployment.

### Out of scope for the initial release

- Creating or issuing official APAAR IDs.
- Direct database access to government infrastructure.
- Scraping protected portals or bypassing access controls.
- Collecting Aadhaar data unnecessarily.
- Claiming official credential authenticity based only on a matching ID.
- Automated rejection of students based solely on fuzzy matching.
- Blockchain deployment without a demonstrated requirement.
- Microservices, Kubernetes, or paid infrastructure where a simpler solution suffices.

---

## 3. Product Features

### 3.1 Student Record Management

- Create, view, edit, search, and archive institutional student profiles.
- Associate a profile with an institutional student number.
- Associate an APAAR identifier only through an appropriate, authorized workflow.
- Maintain course, programme, department, admission year, and academic status.
- View academic records in a chronological timeline.
- Display missing fields and data-quality warnings.
- Support pagination, filtering, sorting, and export permissions.
- Preserve record history for relevant changes.
- Prevent duplicate institutional identifiers within the same institution.
- Provide a correction request and review workflow.

### 3.2 Academic Record Management

- Store course, semester, examination, result-reference, and credit information where applicable.
- Record the institution or awarding body that supplied each academic record.
- Store source references and timestamps.
- Validate mandatory fields and permitted value ranges.
- Detect conflicting semester, course, and enrolment information.
- Preserve source records separately from normalized application records.
- Track corrections without silently overwriting authoritative source information.
- Support record import from CSV and approved structured formats.

### 3.3 Bulk Import and Data Quality

Provide a guided import workflow:

1. Upload a CSV file.
2. Validate file type and size.
3. Preview the detected columns.
4. Map input columns to application fields.
5. Validate each row.
6. Identify missing values and duplicate candidates.
7. Preview accepted, rejected, and review-required rows.
8. Confirm the import.
9. Display a summary and downloadable error report.

Requirements:

- Use streaming or bounded processing for larger files.
- Enforce configurable upload limits.
- Reject malformed or unexpected data.
- Use transactions or staged imports to avoid partial corruption.
- Make retries safe and prevent duplicate imports.
- Never log entire student records or sensitive identifiers.
- Provide a clear report for correcting and re-uploading failed rows.

### 3.4 Verification Engine

Implement a deterministic, configurable rules engine.

Example checks:

- Required fields are present.
- Institutional identifiers conform to expected formats.
- Course and institution codes exist in approved reference data.
- Academic record fields are internally consistent.
- Source timestamps and provenance are present.
- A source response matches the expected student and requested purpose.
- Multiple records appear to refer to the same student.
- A previously reviewed record has changed since its last verification.

Each check should produce:

- Rule identifier and version.
- Input source and timestamp.
- Outcome.
- Human-readable explanation.
- Evidence reference.
- Severity.
- Whether manual review is required.

Supported case statuses:

- Draft
- Pending verification
- In progress
- Verified against source
- Demo-validated
- Needs review
- Discrepancy detected
- Failed to verify
- Expired or stale
- Cancelled

A failed external request must never be represented as a verified result.

### 3.5 Duplicate Candidate Detection

Start with deterministic matching, then optionally add explainable fuzzy matching.

Possible matching signals:

- Institutional student identifier.
- Normalized name.
- Institution and programme.
- Admission year.
- Other legally and operationally justified attributes.

Safeguards:

- Do not use APAAR ID alone as proof that two complete profiles are equivalent.
- Avoid logging raw personal attributes used in comparisons.
- Explain which non-sensitive matching signals caused a candidate match.
- Treat uncertain matches as review candidates.
- Require an authorized review before merging records.
- Preserve original identifiers, source references, and audit history.
- Never automatically delete student profiles based on a similarity score.

### 3.6 Verification Case Management

- Create a verification case for a student or academic record.
- Display required checks and their results.
- Assign a case to an authorized reviewer.
- Add internal notes and correction requests.
- Record decisions and reasons.
- Track case history and timestamps.
- Reopen a case when source data changes.
- Distinguish source errors from local data-entry errors.
- Prevent unauthorized users from approving or modifying cases.
- Support safe retry of failed integration requests.

### 3.7 Institutional Dashboard

Display aggregated, permission-filtered metrics:

- Total institutional student records.
- Records pending verification.
- Records verified against an authorized source.
- Locally validated records.
- Discrepancies awaiting review.
- Potential duplicate candidates.
- Recent imports and failed import jobs.
- Verification completion trends.
- Average case processing time.
- Recent security-relevant events.

All demonstration data must be clearly marked as synthetic.

Do not combine demo-validated records with externally verified records when calculating official verification rates.

### 3.8 Audit and Provenance

Maintain a structured audit trail for relevant actions:

- Profile creation and modification.
- Academic record changes.
- Import creation and completion.
- Verification attempts and outcomes.
- Reviewer decisions.
- Consent changes where applicable.
- Permission changes.
- External provider requests and correlation IDs.
- Report generation and permitted data exports.

Audit records should include the actor, action, resource identifier, timestamp, result, and a correlation identifier.

Avoid recording passwords, tokens, full APAAR identifiers, document contents, or unnecessary personal data.

Restrict audit-log modification. A hash chain may be considered as a tamper-evidence enhancement, but a hash chain alone does not guarantee the integrity of an entire system.

### 3.9 Consent and Privacy Workflow

- Record the purpose and context of applicable consent.
- Capture the status and timestamp of the consent interaction.
- Record withdrawal or expiry where applicable.
- Prevent a new optional processing operation when required permission is absent.
- Show the user which information is requested and why.
- Record the lawful basis and applicable authorization requirements for the workflow.
- Provide a data correction request process.
- Define retention and deletion policies.

Consent must not be treated as a universal substitute for other legal requirements or institutional authorization.

### 3.10 Reporting and Export

- Export filtered institutional records where authorized.
- Generate verification summaries.
- Generate import error reports.
- Provide CSV output for compatible workflows.
- Include generation timestamps and source references.
- Mask identifiers by default.
- Log sensitive export actions.
- Enforce server-side export permissions and row limits.
- Avoid publicly accessible report URLs containing student data.

### 3.11 Notifications

Optional notification functionality:

- Pending verification reminders.
- Import completion notifications.
- Correction request updates.
- Failed integration job alerts.
- Case assignment notifications.

Initially, use in-application notifications. Email can be added if a suitable free-tier provider and its usage limits are available.

Do not send sensitive academic or identity details in notification messages.

### 3.12 Optional Advanced Features

Only add these after the main workflow is reliable:

- Explainable fuzzy matching.
- OCR for supported academic documents.
- Document metadata and integrity checks.
- Signed verification report generation.
- Institution-specific validation rules.
- Multi-institution reporting.
- Read-only API integrations.
- Idempotent background jobs and retry policies.
- Accessibility improvements and localization.
- Analytics on data-quality trends.
- Integration health monitoring.

Advanced features must not imply official endorsement or government integration.

---

## 4. Research Gaps and Validation Plan

This section records research hypotheses to investigate. These are not claims that existing APAAR, ABC, DigiLocker, or institutional systems lack the listed capabilities.

### 4.1 Existing Ecosystem

APAAR describes its relationship with ABC and DigiLocker and its role in student academic identity and record management.

API Setu lists ABC/APAAR-related APIs, including identity verification and student record retrieval interfaces. Availability of an API listing does not establish eligibility for access, production credentials, or permission to process every type of student record.

Official references:

- APAAR portal: https://apaar.education.gov.in/
- APAAR FAQs: https://apaar.education.gov.in/faqs
- APAAR terms of use: https://apaar.education.gov.in/termsofuse
- ABC API collection: https://directory.apisetu.gov.in/api-collection/abc
- API Setu: https://apisetu.gov.in/
- API Setu access and use documentation: https://docs.apisetu.gov.in/

### 4.2 Research Hypotheses

**Gap A — Institutional workflow fragmentation**

Hypothesis: Institutions may require additional tools to coordinate record correction, discrepancy review, and internal verification tasks across their existing systems.

Research method:
- Review available institutional systems and published workflows.
- Interview relevant institutional users where feasible.
- Map current steps, handoffs, delays, and duplicate data entry.
- Compare the current workflow with the proposed case-management workflow.

Potential contribution:
- Unified verification queue.
- Traceable correction workflow.
- Reduced repetitive data entry.

**Gap B — Data quality and reconciliation**

Hypothesis: Imported academic records may contain inconsistent formats, missing fields, or duplicate profiles that require manual reconciliation.

Research method:
- Create synthetic datasets with known data-quality defects.
- Measure precision and recall for duplicate candidate detection.
- Compare deterministic rules with explainable fuzzy matching.
- Evaluate false-positive and false-negative cases.

Potential contribution:
- Configurable rules engine.
- Explainable discrepancy reports.
- Human-reviewed duplicate resolution.

**Gap C — Source provenance and verification status**

Hypothesis: Users may benefit from a consistent interface distinguishing local validation, institutional confirmation, and verification against an authorized external source.

Research method:
- Examine published API specifications and institutional procedures.
- Document the evidence available for each verification state.
- Test whether users can distinguish a mock result from an authoritative response.

Potential contribution:
- Explicit verification-state model.
- Source and timestamp tracking.
- Clear failed, stale, and inconclusive outcomes.

**Gap D — Interoperability**

Hypothesis: Integration effort may vary across institutional data formats and authorized academic record providers.

Research method:
- Inspect published OpenAPI specifications where available.
- Compare data fields, authentication methods, error formats, and versioning.
- Build adapters against synthetic fixtures.
- Record missing fields and unresolved mapping decisions.

Potential contribution:
- Provider-independent adapter interface.
- Normalized internal data model.
- Contract tests and integration health checks.

**Gap E — Privacy and least-privilege access**

Hypothesis: Academic record workflows benefit from purpose-limited access, identifier masking, and auditable information disclosure.

Research method:
- Conduct a data inventory.
- Map information to business purposes.
- Threat-model unauthorized record access.
- Test cross-institution access boundaries.
- Review relevant legal and institutional requirements.

Potential contribution:
- Institution-scoped authorization.
- Data minimization.
- Auditable exports and verification decisions.

**Gap F — Operational transparency**

Hypothesis: Clear explanations of discrepancies may reduce review effort compared with opaque pass/fail outcomes.

Research method:
- Define representative test cases.
- Compare rule-only outcomes with explanation-rich outcomes.
- Measure review completion time and reviewer agreement where participants are available.

Potential contribution:
- Human-readable findings.
- Evidence references.
- Versioned validation rules.

### 4.3 Research Deliverables

Create and maintain:

- `docs/research/landscape-review.md`
- `docs/research/api-access-assessment.md`
- `docs/research/data-quality-experiments.md`
- `docs/research/privacy-threat-model.md`
- `docs/research/limitations-and-assumptions.md`

Every research conclusion should identify its evidence, date, limitations, and whether it has been independently validated.

Do not claim novelty solely because a feature is not present in the sources reviewed.

---

## 5. Technology Stack

### Frontend

- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- React Router
- TanStack Query
- React Hook Form
- Zod
- Recharts
- Vitest
- React Testing Library
- Playwright for end-to-end testing

### Backend

- Node.js LTS
- TypeScript
- Express
- Zod
- Prisma ORM
- PostgreSQL
- OpenAPI/Swagger
- Pino or an equivalent structured logger
- Vitest and Supertest

### Development and DevOps

- Git and GitHub
- GitHub Actions
- Docker and Docker Compose for local reproducibility
- ESLint
- Prettier
- npm workspaces
- Environment-based configuration
- Dependabot or equivalent dependency-update tooling

### Optional supporting services

- S3-compatible storage for approved document workflows.
- A managed email provider for notifications.
- Sentry or an equivalent error-monitoring service.
- Redis only if a later requirement justifies a shared cache or queue.

Avoid adding optional services before a demonstrated need.

### Technology Rationale

TypeScript allows frontend and backend code to share validation schemas and data contracts.

PostgreSQL provides relational constraints and transactional consistency for students, academic records, institutions, consent, and verification history.

Prisma simplifies schema management, migrations, and type-safe database access.

A modular monolith reduces deployment and operational complexity while preserving clear internal boundaries.

---

## 6. High-Level Architecture

```text
Browser
  |
  v
React + TypeScript
  |
  | HTTPS / JSON
  v
Express REST API
  |
  +-- Authentication and sessions
  |
  +-- Institution-scoped authorization
  |
  +-- Student and academic record module
  |
  +-- Import and data-quality module
  |
  +-- Verification case management
  |
  +-- Rules and duplicate detection engine
  |
  +-- Audit and reporting module
  |
  +-- Integration adapter interface
         |
         +-- Mock provider for development
         |
         +-- Authorized external provider
  |
  v
Prisma ORM
  |
  v
PostgreSQL
```

### Architecture principles

- Keep business logic out of React components and route handlers.
- Use a modular monolith initially.
- Separate API contracts from database implementation details.
- Enforce authorization in backend services.
- Validate all external and user-provided data.
- Use transactions for related database changes.
- Keep integration credentials exclusively on the server.
- Use explicit timeouts and safe retries for external requests.
- Design external integration operations to be idempotent where possible.
- Track the source and provenance of academic data.
- Use migrations to evolve the schema safely.
- Avoid storing raw external responses unless required and approved.

---

## 7. Proposed Repository Structure

```text
apaar-student-verification/
|
+-- apps/
|   +-- web/
|   |   +-- src/
|   |       +-- app/
|   |       +-- components/
|   |       +-- features/
|   |       +-- layouts/
|   |       +-- hooks/
|   |       +-- lib/
|   |       +-- routes/
|   |       +-- styles/
|   |
|   +-- api/
|       +-- src/
|           +-- config/
|           +-- middleware/
|           +-- modules/
|           |   +-- auth/
|           |   +-- institutions/
|           |   +-- students/
|           |   +-- academic-records/
|           |   +-- imports/
|           |   +-- verification/
|           |   +-- audit/
|           |   +-- integrations/
|           +-- services/
|           +-- utils/
|           +-- app.ts
|           +-- server.ts
|
+-- packages/
|   +-- shared/
|       +-- src/
|           +-- schemas/
|           +-- types/
|           +-- constants/
|
+-- prisma/
|   +-- schema.prisma
|   +-- migrations/
|   +-- seed.ts
|
+-- docs/
|   +-- architecture/
|   +-- api/
|   +-- research/
|   +-- security/
|   +-- deployment/
|
+-- tests/
|   +-- integration/
|   +-- e2e/
|   +-- fixtures/
|
+-- .github/
|   +-- workflows/
|
+-- .env.example
+-- .gitignore
+-- docker-compose.yml
+-- package.json
+-- README.md
```

The directory layout may evolve as implementation begins. Keep naming consistent and avoid creating empty abstractions without a clear use.

---

## 8. Database Design

Use PostgreSQL as the primary relational database.

### Proposed entities

| Entity | Purpose |
|---|---|
| `institutions` | Institutional identity and configuration |
| `users` | Application account and authentication metadata |
| `institution_memberships` | Institution-scoped access |
| `students` | Institutional student profile |
| `student_identifiers` | Typed identifiers and protected identifier references |
| `academic_records` | Course, semester, credit, and result metadata |
| `record_sources` | Provenance and source information |
| `consent_records` | Applicable consent or permission history |
| `verification_cases` | Verification workflow state |
| `verification_events` | Individual rule outcomes and decisions |
| `validation_rules` | Configurable validation definitions and versions |
| `import_jobs` | Bulk-import metadata and processing status |
| `import_rows` | Row-level results and error references |
| `audit_logs` | Security-relevant actions and changes |
| `integration_jobs` | External provider request status and retries |
| `notifications` | Non-sensitive notification metadata |

### Database safeguards

- Use UUID primary keys where appropriate.
- Add foreign keys and unique constraints.
- Enforce institution-scoped uniqueness for institutional student identifiers.
- Use transactions for related changes.
- Store UTC timestamps consistently.
- Use indexes for frequent search and filtering.
- Use database constraints for critical invariants.
- Avoid storing unnecessary sensitive identifiers.
- Mask identifiers in application responses.
- Define deletion, retention, and archival policies.
- Never use real student records in automated test fixtures.
- Use separate development, test, and production databases.

### Identifier protection

Prefer not to persist the full APAAR identifier unless a documented requirement and appropriate authorization justify doing so.

Where matching is necessary, consider a keyed HMAC of a normalized identifier for equality checks, with the key held outside the database.

A plain hash of a structured or enumerable identifier is not sufficient protection against guessing attacks.

If the application must display the original identifier, evaluate whether encrypted storage is necessary and how key management will work. Do not invent a cryptographic design without reviewing the threat model.

---

## 9. APAAR / ABC Integration Strategy

### 9.1 Integration Constraint

APAAR/ABC-related data must not be assumed to be publicly queryable simply because a website or API catalogue is publicly visible.

The application must not connect directly to an undocumented or private production database.

The preferred integration path is through documented, approved interfaces and their prescribed authentication and authorization processes.

### 9.2 Research and Access Assessment

Before attempting live integration:

1. Review the official APAAR and ABC documentation.
2. Inspect the relevant API Setu API collection and available specifications.
3. Identify the actual API publisher and intended consumer category.
4. Determine whether the use case requires institutional onboarding, approval, contractual authorization, or other prerequisites.
5. Establish the available sandbox and production environments.
6. Obtain credentials through the prescribed official process.
7. Document authentication, token expiry, scopes, rate limits, errors, and permitted fields.
8. Confirm the purpose, data minimization, retention, and disclosure requirements.
9. Test only against the permitted environment.
10. Record the integration's limitations and approval status.

An API catalogue entry is evidence that an interface is listed, not evidence that the project already has access.

### 9.3 Integration Adapter Pattern

Implement a provider-independent interface.

Illustrative TypeScript contract:

```typescript
export interface AcademicRecordProvider {
  readonly providerName: string;

  verifyIdentifier(input: {
    identifier: string;
    purpose: string;
    correlationId: string;
  }): Promise<ProviderVerificationResult>;

  fetchAcademicRecords?(input: {
    identifier: string;
    correlationId: string;
  }): Promise<ProviderAcademicRecordsResult>;
}
```

Define normalized response types that explicitly represent:

- Verified against the named provider.
- Not found.
- Inconclusive.
- Unauthorized.
- Provider unavailable.
- Rate limited.
- Invalid request.
- Stale response.
- Unsupported operation.

Use discriminated unions rather than ambiguous boolean values.

Never interpret a timeout, HTTP error, or missing response as successful verification.

### 9.4 Development Modes

**Mode A — Synthetic provider**

Default local-development implementation.

- Uses synthetic students and deterministic fixtures.
- Simulates successful and failed responses.
- Does not contact official services.
- Labels all results as demo-only.
- Supports repeatable integration tests.

**Mode B — Institution-supplied records**

Accept records supplied by an authorized institution through supported imports.

- Validate the schema and source metadata.
- Record who supplied the information.
- Distinguish internal validation from external verification.
- Do not assume imported information is authoritative.

**Mode C — Authorized API integration**

Implement only after access has been approved.

- Use the documented authentication mechanism.
- Store secrets in server-side environment configuration.
- Apply timeouts, rate limits, and safe retry policies.
- Validate provider responses.
- Record provider references and timestamps.
- Minimize returned and persisted data.
- Test revocation, expired tokens, provider downtime, and access denial.

### 9.5 DigiLocker Integration

If an applicable authorized DigiLocker workflow is available:

- Follow the official partner integration documentation.
- Use the documented authorization and consent flow.
- Validate the returned state and callback.
- Request only the permitted document scopes.
- Validate issuer, document metadata, and applicable signatures or verification evidence.
- Distinguish a document retrieved through an authorized workflow from an internally uploaded document.
- Avoid collecting or storing more document data than necessary.

Do not implement an imitation login page or collect DigiLocker credentials.

### 9.6 Integration Security

- No API secrets in frontend bundles.
- No credentials committed to Git.
- TLS for network connections.
- Strict response validation.
- Provider-specific timeouts.
- Bounded retries with backoff.
- Redacted request and error logs.
- Correlation IDs for troubleshooting.
- Explicit authorization and consent checks where applicable.
- No automatic trust in arbitrary response fields.
- No undocumented endpoints or access-control bypasses.

### 9.7 Integration Deliverable

The initial release must work fully without live APAAR credentials.

Live integration is an enhancement gated on access, documentation, and approval. The absence of credentials must not prevent the team from demonstrating record management and verification workflows.

---

## 10. API Design

Use versioned REST endpoints under `/api/v1`.

### Authentication

```text
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/auth/me
```

### Institutions and memberships

```text
GET    /api/v1/institutions
GET    /api/v1/institutions/:id
GET    /api/v1/memberships
```

### Students

```text
GET    /api/v1/students
POST   /api/v1/students
GET    /api/v1/students/:id
PATCH  /api/v1/students/:id
GET    /api/v1/students/:id/records
```

### Imports

```text
POST   /api/v1/imports
GET    /api/v1/imports/:id
GET    /api/v1/imports/:id/errors
POST   /api/v1/imports/:id/confirm
```

### Verification

```text
POST   /api/v1/verifications
GET    /api/v1/verifications
GET    /api/v1/verifications/:id
POST   /api/v1/verifications/:id/decision
POST   /api/v1/verifications/:id/retry
```

### Integration

```text
GET    /api/v1/integrations/status
POST   /api/v1/integrations/verification-requests
GET    /api/v1/integrations/requests/:id
```

### Dashboard and audit

```text
GET    /api/v1/dashboard/summary
GET    /api/v1/audit-logs
GET    /api/v1/reports/verification
```

All endpoints are proposed contracts, not existing official API routes.

Implement pagination, input validation, authorization, rate limiting, structured errors, and OpenAPI documentation.

Never expose raw database models directly as public API responses.

---

## 11. UI/UX Specification

### Design direction

Use a professional institutional administration interface.

Visual principles:

- Clear information hierarchy.
- Consistent spacing and typography.
- Neutral backgrounds and restrained colors.
- High-contrast text.
- Accessible form controls.
- Clear status labels and explanatory text.
- Responsive layouts.
- Minimal unnecessary animations.
- Consistent loading, error, empty, and success states.

Suggested design system:

- Tailwind CSS for styling.
- shadcn/ui for reusable components.
- Lucide icons.
- Recharts for analytical charts.
- React Hook Form and Zod for validated forms.

### Required Screens

**1. Authentication**

- Sign-in form.
- Session-expiry handling.
- Accessible error messages.
- Secure logout.
- No sensitive information in URLs.

**2. Dashboard**

- Student record counts.
- Verification queue summary.
- Data-quality statistics.
- Recent activity.
- Integration health.
- Clearly labeled synthetic demo statistics.

**3. Student Directory**

- Search and filters.
- Server-side pagination.
- Institution and course filters.
- Masked identifier display.
- Record status.
- Profile navigation.

**4. Student Profile**

- Institutional profile.
- Academic record timeline.
- Data provenance.
- Verification history.
- Correction workflow.
- Restricted identifier details.

**5. Bulk Import Wizard**

- Upload and validation.
- Column mapping.
- Preview.
- Row-level errors.
- Confirmation.
- Import history.

**6. Verification Workbench**

- Verification case details.
- Source information.
- Rule outcomes.
- Evidence references.
- Review notes.
- Authorized decisions.
- Retry and stale-result handling.

**7. Discrepancy Management**

- Filterable discrepancy queue.
- Explanation of the mismatch.
- Assigned review status.
- Correction request.
- Resolution history.

**8. Audit and Reports**

- Filterable audit history.
- Date range selection.
- Authorized exports.
- Summary reports.
- Source and generation timestamps.

**9. Settings and Integration Status**

- Institution configuration.
- Validation rule settings.
- Integration environment.
- Last successful connection.
- Provider error summaries.
- Credential status without revealing secrets.

### UX Acceptance Criteria

- A user can find a student without loading the complete database.
- Forms explain validation failures.
- Import errors identify the affected row and field.
- Every verification result explains its meaning.
- Demo results are visually distinguishable from authoritative results.
- Sensitive identifiers are masked by default.
- Destructive actions require appropriate confirmation.
- Keyboard navigation works on essential workflows.
- Charts have accessible labels or equivalent summaries.
- Mobile layouts remain usable without horizontal overflow.

---

## 12. Authentication and Authorization

Implement secure account authentication and institution-scoped authorization.

- Use a well-maintained authentication library or identity provider.
- For cookie-based sessions, enable Secure, HttpOnly, and appropriate SameSite attributes in production.
- Apply CSRF protection when required by the chosen authentication design.
- Hash passwords with a modern password-hashing algorithm if password authentication is implemented directly.
- Use generic authentication failure messages.
- Enforce rate limits on login and sensitive endpoints.
- Check permissions in backend services, not only in the UI.
- Restrict student records to authorized institutional contexts.
- Enforce least privilege for exports and audit access.
- Record security-relevant authorization failures.
- Test horizontal and vertical privilege escalation scenarios.

Do not rely on a user-supplied institution ID to authorize access to that institution's records.

---

## 13. Privacy, Security, and Compliance

Treat student academic data as sensitive personal information.

Design the platform with reference to applicable Indian data-protection requirements, including the Digital Personal Data Protection Act, 2023, and the Digital Personal Data Protection Rules, 2025, while confirming which provisions are in force and applicable to the actual processing activity.

References:

- DPDP Rules, 2025: https://www.meity.gov.in/
- India Code: https://www.indiacode.nic.in/
- APAAR terms: https://apaar.education.gov.in/termsofuse

Security requirements:

- Data minimization.
- Purpose limitation.
- Institution-scoped access control.
- Identifier masking.
- Encryption in transit.
- Appropriate protection at rest.
- Secret management.
- Secure database connections.
- Audit trails.
- Data retention and deletion policies.
- Secure file uploads.
- Dependency updates.
- Backup and recovery planning.
- Incident response documentation.
- Appropriate privacy notices and permission workflows.

A hackathon prototype is not automatically compliant merely because these controls are implemented. A production deployment requires a separate legal, security, and operational assessment.

---

## 14. Testing Strategy

### Unit tests

Test:

- Validation rules.
- Identifier normalization.
- Duplicate candidate matching.
- Status transitions.
- Permission decisions.
- Import field mapping.
- Error handling.

### API integration tests

Test:

- Database constraints.
- Authentication and authorization.
- Student CRUD operations.
- Import transactions.
- Verification case creation.
- Reviewer decisions.
- Audit logging.
- Provider failures.
- Pagination and filtering.

### End-to-end tests

Test the complete workflow:

1. Authenticate.
2. Create or import synthetic student data.
3. Run validation.
4. Review discrepancies.
5. Record a decision.
6. Inspect the audit trail.
7. Generate an authorized report.

### Security tests

Test:

- Cross-institution record access.
- Unauthorized exports.
- Invalid session handling.
- Malformed input.
- Oversized uploads.
- Injection attempts.
- Rate limits.
- Secret leakage.
- Insecure direct object references.
- Sensitive information in logs.

### Integration contract tests

Test:

- Valid provider responses.
- Invalid response schemas.
- Expired credentials.
- Permission denial.
- Timeouts.
- Rate limiting.
- Duplicate requests.
- Provider unavailability.

### Quality gates

Every pull request should pass:

- Linting.
- Type checking.
- Unit tests.
- Relevant integration tests.
- Production build.

---

## 15. Local Development

### Prerequisites

- Node.js LTS.
- npm.
- Git.
- Docker Desktop, if using local PostgreSQL through Docker.
- A code editor such as VS Code.

### Environment configuration

Maintain `.env.example` with variable names and placeholder values only.

Possible variables:

```dotenv
NODE_ENV=development
PORT=4000
DATABASE_URL=
SESSION_SECRET=
WEB_ORIGIN=http://localhost:5173
API_BASE_URL=http://localhost:4000
INTEGRATION_MODE=mock
```

Do not commit `.env` files, API keys, database passwords, or real student data.

### Development workflow

1. Install workspace dependencies.
2. Configure local environment variables.
3. Start PostgreSQL.
4. Apply Prisma migrations.
5. Seed synthetic data.
6. Start the backend.
7. Start the frontend.
8. Run tests.
9. Verify the end-to-end workflow.

Use synthetic data for development and automated testing.

---

## 16. Free-Tier Deployment Proposal

The initial application should be deployable using free-tier or free-quota services, subject to their current terms, quotas, availability, and account eligibility.

Free tiers can change. Confirm current limits before choosing the final deployment configuration.

### Proposed deployment

**Frontend: Vercel**

- Deploy the Vite frontend from GitHub.
- Configure the correct workspace root and build command.
- Set the production API URL.
- Enable HTTPS through the hosting platform.

Alternative: Cloudflare Pages or another suitable free static-hosting tier.

**Backend: Render**

- Deploy the Express API as a web service.
- Configure the workspace-specific build and start commands.
- Set production environment variables.
- Add a health-check endpoint.
- Restrict CORS to approved frontend origins.

Confirm whether the selected plan currently permits the required web service and whether idle services may sleep.

Alternative: another suitable managed application-hosting free tier.

**Database: Neon PostgreSQL**

- Provision a managed PostgreSQL database on an available free tier.
- Store the connection string as a backend secret.
- Use TLS and appropriate database credentials.
- Apply migrations during controlled deployment.
- Monitor storage, connection, and compute limits.

Alternative: another managed PostgreSQL provider with an appropriate free plan.

**CI/CD: GitHub Actions**

- Run linting and type checks.
- Execute unit and API tests.
- Build the frontend and backend.
- Deploy only after successful checks.
- Keep deployment credentials in GitHub Secrets or the hosting platform's secret manager.

### Deployment Architecture

```text
GitHub Repository
       |
       v
GitHub Actions
       |
       +-------------------+
       |                   |
       v                   v
Frontend Hosting       API Hosting
       |                   |
       | HTTPS             | TLS
       |                   v
       +------------> PostgreSQL
```

### Deployment Requirements

- Production environment variables.
- Restricted CORS.
- HTTPS.
- Health checks.
- Database migrations.
- Synthetic production-demo seed data.
- Error logging without sensitive payloads.
- Dependency scanning.
- Backup and recovery plan appropriate to the chosen provider.
- No public database access unless specifically required and secured.
- No sensitive information in public frontend assets.
- Documented limitations of free-tier hosting.

### Deployment Caveats

Free hosting is appropriate for a prototype, not automatically for a production academic identity system.

Free-tier limitations may include sleeping services, limited database storage, restricted connection counts, backup limitations, and resource quotas.

Do not promise high availability, production-grade disaster recovery, or a service-level agreement without verifying that the selected infrastructure supports them.

---

## 17. CI/CD and Repository Practices

Use a single GitHub repository with a modular monorepo layout.

Recommended branch policy:

- `main`: stable and deployable.
- `feature/*`: isolated feature development.
- `fix/*`: bug fixes.

Recommended pull-request checks:

- ESLint.
- TypeScript compilation.
- Unit tests.
- API integration tests.
- Build checks.
- Dependency vulnerability checks.

Repository rules:

- Use small, descriptive commits.
- Require pull requests for important changes.
- Do not commit secrets.
- Keep `.env.example` updated.
- Maintain database migrations.
- Document API changes.
- Review schema changes before merging.
- Use synthetic test fixtures.
- Keep the README aligned with the implemented product.

---

## 18. Implementation Roadmap

### Phase 1 — Foundation

- Confirm requirements.
- Finalize architecture.
- Create repository structure.
- Scaffold React and Express.
- Configure PostgreSQL and Prisma.
- Establish linting and tests.
- Prepare UI wireframes.

### Phase 2 — Core Records

- Implement authentication.
- Implement institution-scoped authorization.
- Build student profiles.
- Build academic record management.
- Add search, filtering, and pagination.
- Add synthetic seed data.

### Phase 3 — Validation

- Build CSV import.
- Implement deterministic rules.
- Add discrepancy detection.
- Add duplicate candidate matching.
- Build verification case management.
- Add reviewer decisions.

### Phase 4 — Trust and Reporting

- Implement audit history.
- Add record provenance.
- Implement consent or permission tracking where applicable.
- Add reports and exports.
- Add security and accessibility checks.

### Phase 5 — Integration Readiness

- Define the provider adapter.
- Build a mock integration.
- Add contract tests.
- Document official access prerequisites.
- Implement a real adapter only when authorized.

### Phase 6 — Deployment

- Configure CI.
- Deploy frontend and backend.
- Provision managed PostgreSQL.
- Apply migrations.
- Run smoke tests.
- Verify authorization boundaries.
- Prepare the demonstration.

---

## 19. Definition of Done

The MVP is complete when:

- The application runs locally from documented instructions.
- A synthetic dataset can be imported.
- Student profiles and academic records can be managed.
- Validation rules produce explainable outcomes.
- Duplicate candidates can be reviewed.
- Verification cases have traceable state transitions.
- Unauthorized cross-institution access is blocked.
- Sensitive identifiers are masked.
- Audit events are recorded.
- Reports reflect correct verification categories.
- Unit and integration tests pass.
- The application is deployed to a reachable demonstration environment.
- No official integration is claimed without an authorized successful connection.
- Known limitations are documented.

---

## 20. Success Metrics

Measure the prototype using repeatable synthetic datasets.

Suggested metrics:

- Percentage of valid import rows accepted.
- Number of invalid rows correctly identified.
- Duplicate candidate precision and recall.
- False-positive rate for duplicate matching.
- Average processing time per import.
- Average time to review a verification case.
- Percentage of actions correctly captured in audit logs.
- Number of authorization boundary tests passed.
- API response time under a documented test load.
- Successful deployment and recovery test results.

Establish baselines before claiming improvement. Do not report fabricated performance gains.

---

## 21. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Official API access unavailable | Use synthetic fixtures and institution-supplied authorized records |
| API specification changes | Isolate integrations behind adapters and contract tests |
| False duplicate matches | Require review and preserve original records |
| Personal data exposure | Minimize collection, mask identifiers, restrict access |
| Inconsistent academic records | Track source provenance and version changes |
| Free-tier limits | Monitor quotas and keep a local development path |
| Unauthorized cross-institution access | Enforce institution-scoped authorization in the backend |
| Misleading verification status | Use explicit, source-specific status definitions |
| Dependency vulnerabilities | Run automated dependency checks and update regularly |
| Unverified research assumptions | Label hypotheses and collect evidence before claiming gaps |

---

## 22. Final Project Positioning

The platform is intended to complement existing academic identity and record ecosystems by providing a structured institutional workflow for record management, data quality, discrepancy resolution, and auditable verification.

Its main differentiators should be demonstrated through:

- Explainable data validation.
- Human-reviewed discrepancy resolution.
- Clear separation of internal validation and authoritative verification.
- Provider-independent integration design.
- Institution-scoped authorization.
- Privacy-conscious data handling.
- Reproducible testing and transparent research.
- A deployable, maintainable software architecture.

The first release should prioritize correctness, usability, security, and a complete end-to-end demonstration over unnecessary complexity.

---

## 23. Reference Sources

1. APAAR official portal: https://apaar.education.gov.in/
2. APAAR FAQs: https://apaar.education.gov.in/faqs
3. APAAR terms of use: https://apaar.education.gov.in/termsofuse
4. Academic Bank of Credits API collection on API Setu: https://directory.apisetu.gov.in/api-collection/abc
5. API Setu: https://apisetu.gov.in/
6. API Setu standard operating procedures: https://apisetu.gov.in/sop
7. Digital Personal Data Protection Act and related resources: https://www.indiacode.nic.in/
8. Ministry of Electronics and Information Technology: https://www.meity.gov.in/

Consult the current official documentation and relevant approvals before implementing external data access or deploying a system that processes real student records.

---

**Project status:** Initial development specification. Features, architecture, integrations, and deployment options described here are proposed and should not be interpreted as already implemented or approved for production use.