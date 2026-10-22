# Synthetic source dataset timings

**Measured:** 2026-10-23, local Windows environment, Python 3.11.9, SQLite 3.45.1. The harness used one freshly initialized temporary SQLite database and synthetic records only. It exercised CSV parsing/validation, upload preview/staging, confirmation writes, version diff, comparison service, and the full comparison route with audit persistence. Latest run exit code: 0.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe tests\benchmark_source_datasets.py
```

| Rows | Parse + validation | Upload + stage | Preview diff + render | Confirm + write | Version diff | Compare service | Compare route + audit |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.0153 s | 0.1212 s | 0.0676 s | 0.1754 s | 0.0155 s | 0.0008 s | 0.1536 s |
| 4,000 | 0.1255 s | 0.2542 s | 0.0735 s | 0.3686 s | 0.0521 s | 0.0040 s | 0.1774 s |
| 8,000 | 0.2201 s | 0.4317 s | 0.1707 s | 0.4422 s | 0.0955 s | 0.0062 s | 0.1407 s |

These are single-run wall-clock observations on a development machine, not controlled benchmarks or service-level guarantees. Timings include local process and SQLite variability. The configured limits remain 2 MB and 10,000 rows.
