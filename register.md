# Change Register

**Project:** APAAR Student Data Management & Verification Platform  
**Repository:** `sih2026-mitaoe/apaar-student-verification`  
**Maintainer / requested attribution:** Rugved0149  
**Release:** Local demo package v1.0  
**Status:** Prototype; external APAAR integration not implemented.

## Changes included
- Added Flask application with login/logout and dashboard.
- Added SQLite schema and synthetic seed records.
- Added student list/search/pagination, create, edit, detail and soft-archive workflows.
- Added deterministic local validation and review findings.
- Added CSV preview, row validation, explicit transactional confirmation, history, and repeat-file protection.
- Added CSV export that intentionally excludes APAAR identifiers.
- Added audit log page and `/health` endpoint.
- Added responsive styling and templates.
- Added `requirements.txt`, `.env.example`, `.gitignore`, `run.cmd`, and README.
- Added pytest smoke tests.
- Documented the limitation that local checks are not official APAAR verification.

## Known limitations / next steps
- No APAAR/ABC/DigiLocker API connection.
- Demo authentication uses one seeded account; change its password before any shared use.
- Login throttling and CSRF protections are implemented for the demo; user administration, persistent rate limiting, and production identity management remain incomplete.
- SQLite is the implemented authoritative store for the local demo. A production database/deployment assessment remains separate work.
- Review privacy, security, data retention, and institutional authorization before real student data is used.

## Attribution note
Rugved0149 is recorded here as the requested project attribution. This file does not assert that any remote GitHub changes were pushed by this release.