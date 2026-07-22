# Transcript Validation Script

Checks a folder of student-submitted transcript `.txt` files and reports which
ones are usable vs. faulty (and why), as a CSV.

This mirrors the validation logic used by the Qualtrics upload form, so a
file that passes here would also pass on upload.

## Requirements

- Python 3 

## Usage

Run from the terminal, pointing it at the folder of `.txt` transcripts:

```bash
python3 transcript_validation_pipeline_v1.py /path/to/transcripts_folder
```

This writes `validation_report.csv` in the current directory and prints a
summary, e.g.:

```
Checked 42 files.
  Passed: 38
  Failed: 4
Report written to validation_report.csv
```

### Custom output path

```bash
python3 transcript_validation_pipeline_v1.py /path/to/transcripts_folder -o results/my_report.csv
```

## Reading the report

The CSV has these columns:

| Column | Meaning |
|---|---|
| `filename` | the transcript file |
| `status` | `pass` or `fail` |
| `format` | `A`, `B`, `raw-dump`, or `unrecognized` |
| `failed_checks` | reasons the file was rejected (these determine pass/fail) |
| `info_flags` | older, non-blocking checks - FYI only, don't affect pass/fail |
