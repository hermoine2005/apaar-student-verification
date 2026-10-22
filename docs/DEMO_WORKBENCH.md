# Isolated synthetic workbench rehearsal

This rehearsal uses a separate SQLite file. It does not overwrite or point to `instance/apaar_demo.db` or the legacy API database. Use only synthetic data.

## Start a new isolated instance

In PowerShell from the repository root:

```powershell
$demoPath = Join-Path $env:TEMP ('apaar-workbench-demo-' + [guid]::NewGuid().ToString('N') + '.db')
if (Test-Path -LiteralPath $demoPath) { throw 'Choose a new database filename; existing demo data is preserved.' }
$env:APAAR_DB_PATH = $demoPath
$env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:DEMO_ADMIN_PASSWORD = Read-Host 'Choose a local demo admin password'
$env:HOST = '127.0.0.1'
$env:PORT = '5010'
python app.py
```

The first start initializes this new database and inserts the application's four synthetic starter records. Sign in as `admin` with the password entered above. Keep this process running for the walkthrough. Do not unset `APAAR_DB_PATH` in this shell before stopping the demo app.

## Judge walkthrough

1. Open **Students** and inspect `DEMO-1001`. Its stored `Verified` label is an internal demo status, not an official verification result.
2. Open **Students > Add student**. Create a synthetic profile with a unique institutional ID, a name similar to one seeded profile, and leave course/semester blank. The record summary shows quality findings and a direct route to open a case.
3. Open **Review queue** and select **Run duplicate scan**. Review the candidate signals and compare the linked records. A reviewer records a decision and reason; no records are merged.
4. Use the record summary to open a case for the incomplete record. The form preselects that student. The case appears in the central actionable-work list and its timeline.
5. To demonstrate assignment and reviewer separation, use **Users & access** to create a verifier account with a strong local password. In the **Reviewer assignment** section of the Review queue, assign the active case to that verifier. Sign out, sign in as that reviewer, and move the case through `in_review` to `resolved` with a reason. Assignment appears in the case timeline and audit history; the person who created the case cannot resolve it.
6. Open the student detail again. The internal case state, quality findings, duplicate review, and case activity links are grouped in the record summary.
7. Open **Audit history** and verify the case activity. Use **Download filtered case CSV** in Review queue to demonstrate a tenant-scoped report that excludes student names and codes.
8. For the import path, open **Import records** and preview `static/sample_students.csv`. The preview clearly says it has not written records. Confirm it, then use its links to reach the student directory and review workbench.

The seeded users, students, and sample file are synthetic. The application does not issue APAAR IDs or connect to APAAR, ABC, DigiLocker, or government systems.

## Institution-provided source dataset comparison

For a clean isolated session, start a new database in `%TEMP%` (keep the server process in the same PowerShell window):

```powershell
$demoPath = Join-Path $env:TEMP ('apaar-source-demo-' + [guid]::NewGuid().ToString('N') + '.db')
$env:APAAR_DB_PATH = $demoPath
$env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
$env:DEMO_ADMIN_PASSWORD = Read-Host 'Choose a local demo admin password'
$env:HOST = '127.0.0.1'
$env:PORT = '5011'
python app.py
```

On a fresh database, sign in as `admin` using the password entered at startup. The starter student `DEMO-1001` is synthetic. Create a reference CSV in a second PowerShell window:

```powershell
$sourceCsv = Join-Path $env:TEMP 'apaar-source-match.csv'
@'
institution_student_id,full_name,course,semester,email
DEMO-1001,Aarav Sharma,Computer Engineering,4,aarav@example.test
'@ | Set-Content -LiteralPath $sourceCsv -Encoding utf8
```

Open `http://127.0.0.1:5011/source-datasets`, enter a dataset name such as `Synthetic Registrar Snapshot`, select the CSV, inspect the preview, then confirm the import. Open **Students**, select the `DEMO-1001` profile, and compare against the dataset. The result should be `MATCH`. Change the CSV name or course, give it a distinct file name, and import it as another version of the same named dataset to demonstrate a `MISMATCH`; the result is sent to the review queue. A CSV with a different institutional student ID produces `NOT_FOUND`; missing compared values or a pending duplicate candidate require review. Duplicate source IDs are rejected during preview.

Only synthetic values are used. Source data is stored separately from operational student records. Confirmation does not modify a student, and comparison does not merge or update records. The outcome is a comparison against institution-provided data, never official APAAR/ABC/DigiLocker verification. Uploaded SQLite databases and filesystem paths are not supported. The file uses the existing database schema and is initialized additively on startup; use a newly created disposable database for rehearsal.
