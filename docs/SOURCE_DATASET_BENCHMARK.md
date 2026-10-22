# Synthetic source dataset timings

**Measured:** 2026-10-23, local Windows environment, Python 3.11.9, SQLite 3.45.1. The harness used one freshly initialized temporary SQLite database and synthetic records only. It exercised CSV parsing/validation, upload preview/staging, confirmation writes, version diff, comparison service, and the full comparison route with audit persistence. Latest run exit code: 0.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe tests\benchmark_source_datasets.py
```

| Rows | Parse + validation | Upload + stage | Preview diff + render | Confirm + write | Version diff | Compare service | Compare route + audit |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.0158 s | 0.0577 s | 0.0351 s | 0.0359 s | 0.0070 s | 0.0005 s | 0.0258 s |
| 4,000 | 0.0572 s | 0.0812 s | 0.0373 s | 0.0888 s | 0.0234 s | 0.0018 s | 0.0345 s |
| 8,000 | 0.1191 s | 0.1697 s | 0.0901 s | 0.1661 s | 0.0485 s | 0.0040 s | 0.0513 s |

These are single-run wall-clock observations on a development machine, not controlled benchmarks or service-level guarantees. Timings include local process and SQLite variability. The configured limits remain 2 MB and 10,000 rows.
