# APAAR backend upgrade

This folder adds working, institution-scoped API workflows to the supplied backend.

## What changed

- Added persistent institution reference dataset tables and version history.
- Added CSV upload validation for UTF-8, required/allowed columns, duplicate source IDs, row limits, and row-level validation.
- Added source comparison endpoint that compares institutional student ID first, returns field-level results, persists provenance/digests, and writes audit events.
- Added a verification-run endpoint that persists local rule results and clearly reports when no external provider is configured.
- Added verification history endpoint.
- Strengthened email syntax and field-length rules; added an institution-scoped duplicate institutional-ID rule.
- Kept every source CSV comparison explicitly non-authoritative. No official APAAR, ABC, or DigiLocker service is contacted.

## API endpoints

All routes are under `/api/v1` and require an authenticated session/account as enforced by the existing `require_actor` decorator.

- `GET /api/v1/source-datasets`
- `POST /api/v1/source-datasets/upload`
- `POST /api/v1/students/<student_id>/compare-source`
- `POST /api/v1/students/<student_id>/verify`
- `GET /api/v1/students/<student_id>/verification-runs`

### Upload a source CSV

Send JSON with `name` and `csv_text`:

```json
{
  "name": "MITAOE reference list",
  "csv_text": "institution_student_id,full_name,email,course,semester\nSYN-000001,Ira Khan,student000001@example.edu,BCA,1\n"
}
```

CSV required columns: `institution_student_id`, `full_name`. Optional columns: `course`, `semester`, `email`. Use student records that belong to the currently authenticated institution. The upload is versioned; uploading again under the same dataset name creates the next version.

### Compare a student

- Latest uploaded dataset: `POST /api/v1/students/5/compare-source` with `{}`.
- Select dataset: `POST /api/v1/students/5/compare-source` with `{"dataset_id":"<dataset-id>"}`.

Possible outcomes include `MATCH`, `MISMATCH`, `NOT_FOUND`, and `REVIEW_REQUIRED`. These outcomes only describe comparison with an institution-uploaded CSV; they are not official APAAR verification.

### Run local verification

`POST /api/v1/students/5/verify` with `{}`. The response includes individual rules, provider state, status, and an explicit note that no official lookup occurred.

Optional synthetic scenario for a local demo only:
`{"mock_scenario":"matched"}` (other accepted values: `not_found`, `mismatch`, `inconclusive`, `unavailable`, `unauthorized`, `malformed`, `stale`). These are fixtures, not real provider results.

### Read history

`GET /api/v1/students/5/verification-runs`

## Integration notes

1. Back up the current `backend` folder and database before replacing files.
2. Replace the project's `backend` folder with this one.
3. Ensure `register_backend(app)` is called by the Flask application.
4. **Ensure `APAAR_DB_PATH` points to the same SQLite database used by the website**, otherwise the API and website may see different student records.
5. Restart the Flask server and sign in with an account that has the appropriate role.
6. These endpoints use JSON bodies, not multipart file upload.

The Python files passed syntax compilation. A live Flask endpoint smoke test could not be run in this packaging environment because Flask is not installed here. Run the app in the project's virtual environment for an integration check.

## Security / scope

- Routes are scoped to the signed-in user's institution.
- Source CSVs are bounded to 2 MB and 10,000 rows by the source parser.
- Only operators/institution admins can upload reference datasets.
- Only verifiers/institution admins can start verification runs.
- Source comparisons and local rule results never claim official authority.
