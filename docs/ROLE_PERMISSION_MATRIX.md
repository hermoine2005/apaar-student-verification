# Institution-scoped role and route matrix

Roles are reloaded from the active user record for page requests and resolved from the signed-in session for API requests. The legacy `admin` role maps to `institution_admin`. Unknown and inactive roles are denied. Every student, case, dataset, duplicate, audit, import, and export query must include the authenticated institution; browser form mutations additionally require CSRF tokens.

| Capability / route family | Institution administrator | Operator | Verification officer | Auditor |
|---|---:|---:|---:|---:|
| Dashboard, student directory/detail, student API reads | Read/write scoped workflows | Read/write permitted records | Read and review | Read only |
| Create/edit student (`/students/new`, `/students/<id>/edit`, `POST/PUT/PATCH /api/v1/students`) | Yes | Yes | No | No |
| Archive/restore student | Yes | No | No | No |
| Operational CSV import/confirm/error report | Yes | Yes | No | Read import page/history only where route permits |
| Institution source CSV preview/confirm and comparison | Yes | Yes | Compare only | No |
| Review queue, duplicate candidates, cases, timelines | Read; create and decide | Read; create case/evidence and scan duplicates | Read; create case, decide candidate/evidence, transition case | Read only |
| Case assignment/reassignment | Yes, to active same-institution verifier | No | No | No |
| Student and case CSV exports | Yes, audited and scoped | Yes, audited and scoped | Yes, audited and scoped | Yes, audited and scoped |
| Audit history/integrity | Yes | No | No | Yes, institution-scoped |
| User directory/create/role/deactivate | Same-institution only; cannot grant administrator | No | No | No |

There is no platform administrator or institution registry. Institution administrators cannot move accounts across institutions, promote another account to administrator, or change their own role. User creation currently sets an initial password; invitation and reset workflows are not implemented. Export permission is explicitly granted to all four institution roles by the current route policy; exported case reports omit student identity/contact fields and are audited.

## Route enforcement map

| Route family | Read roles | Mutation roles | Scope / protection |
|---|---|---|---|
| `/`, `/students`, `/students/<id>` | All four | — | Session-authenticated; SQL constrained by session institution |
| `/students/new`, `/students/<id>/edit` | Admin, operator | Admin, operator | CSRF on POST; institution supplied by server |
| `/students/<id>/archive`, `/restore`, `/students/archived` | Admin | Admin | Student lookup includes institution |
| `/students/export.csv` | All four | — | Institution filter, formula-safe CSV, export audit |
| `/imports` | Admin, operator, auditor | Admin, operator | Institution filter; CSRF on upload/confirm |
| `/source-datasets` and `/confirm` | Admin, operator | Admin, operator | Institution filter; uploaded filename reduced to basename; source CSV excludes APAAR ID |
| `/students/<id>/compare-source`, `/verify` | Admin, operator, verifier | Admin, operator, verifier | Student/source data constrained to actor institution; CSRF |
| `/api/v1/students`, cases, review, duplicate lists, timelines | All four where route is read-only | Per API route below | `require_actor`; SQL institution predicates |
| `/api/v1/students` create/update, dry-run import, duplicate scan, review case/evidence creation | — | Admin, operator (case creation also verifier) | `require_actor`; CSRF; payload validation |
| `/api/v1/review/candidates/*/decision`, case transitions, evidence decision | — | Admin, verifier | `require_actor`; explicit state/decision checks and audit |
| `/api/v1/review/cases/*/assignment` | — | Admin only | Same-institution active verifier required; assignment history/audit |
| `/api/v1/reports/cases.csv` | All four | — | Filtered institution query, 500-row bound, minimal columns, formula-safe, export audit |
| `/api/v1/audit/*`, `/audit` | Admin, auditor | — | Institution scoped; read-only |
| `/admin/users*` | Admin | Admin | Same institution; bounded assignable roles; sensitive actions audited; CSRF |
| `/health`, `/api/v1/health` | Public health status only | — | Does not expose database or configuration values |

The route map reflects current decorators and query predicates, not a claim of a formal independent security certification. Regression tests in `tests/test_backend_foundation.py`, `tests/test_app.py`, and `tests/test_source_datasets.py` cover representative role denies, cross-institution IDs and exports, CSRF, assignment, and read-only behavior. Add tests alongside any newly introduced route or permission.
