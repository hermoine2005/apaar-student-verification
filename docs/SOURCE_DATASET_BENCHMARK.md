# Synthetic source dataset timings

**Measured:** 2026-10-23, local Windows environment, Python 3.11.9, SQLite 3.45.1. The harness used one freshly initialized temporary SQLite database and synthetic records only. It exercised CSV parsing/validation, upload preview/staging, confirmation writes, version diff, comparison service, and the full comparison route with audit persistence.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe tests\benchmark_source_datasets.py
```

| Rows | Parse + validation | Upload + stage | Preview diff + render | Confirm + write | Version diff | Compare service | Compare route + audit |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.0151 s | 0.0654 s | 0.0299 s | 0.0353 s | 0.0048 s | 0.0004 s | 0.0256 s |
| 4,000 | 0.0589 s | 0.0868 s | 0.0311 s | 0.1029 s | 0.0222 s | 0.0017 s | 0.0400 s |
| 8,000 | 0.1329 s | 0.1937 s | 0.0792 s | 0.1614 s | 0.0421 s | 0.0028 s | 0.0493 s |

These are single-run wall-clock observations on a development machine, not controlled benchmarks or service-level guarantees. Timings include local process and SQLite variability. The configured limits remain 2 MB and 10,000 rows.
