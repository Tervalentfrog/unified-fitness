# Unified Fitness

A local-first, single-user application for importing FitNotes strength history and
Strava running history into SQLite, then querying measured trends from a console.

**Status:** FitNotes v22 ingestion and offline strength summaries are implemented.

## Development setup

Use Python 3.11 or newer. From the repository root in PowerShell:

~~~
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
~~~

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python`.
The application uses the Python standard library and runs offline.

## Import and summarize

Place a standalone FitNotes SQLite v22 export in `data/`. Replace
`your-backup.fitnotes` with its filename. Use `--assume-performed` only
after confirming the sets in that export were performed.

~~~
.\.venv\Scripts\unified-fitness.exe --help
.\.venv\Scripts\unified-fitness.exe --db data/fitness.sqlite3 import-fitnotes data/your-backup.fitnotes --assume-performed
.\.venv\Scripts\unified-fitness.exe --db data/fitness.sqlite3 summary
~~~

The default database path is `data/unified-fitness.sqlite3`. On macOS/Linux
the command is `.venv/bin/unified-fitness`. Summary prints JSON with overall
and per-exercise set and repetition totals and the overall count of distinct
recorded training dates. Treat report output as personal data.

The importer accepts valid type-0 rows with zero distance and duration. It
preserves raw weights and codes and leaves normalized load, unit, load kind,
and set order empty. Both raw flags are retained. Matching source IDs update
the stored payload when it changes. Missing IDs are retained. Real ID stability
across edits, reorders, and restores remains unverified, and importing an older
snapshot can overwrite newer values for matching IDs.

Import output counts inserted, updated, unchanged, rejected, and unsupported
sets. Stderr gives counts by reason and separate warnings. Exit codes are 0
for success, 1 for a fatal error, 2 for invalid usage, and 3 for a committed
import with rejected or unsupported rows.

The milestone review passed all 26 tests and verified two imports of the
confirmed backup into a fresh database. See the [review results](planning/handoff.md#milestone-review)
for the integrity, normalization, and repeat-import checks.

## Configuration and privacy

`.env.example` documents proposed settings, not a working configuration loader.
No API key is needed now. Later code will read process environment variables;
copying the template to `.env` alone will not load it automatically.

Store private exports and databases under `data/`. Keep credentials, raw data,
personal reports, and transcripts out of Git. Only synthetic test fixtures belong
in `tests/fixtures/`. Review staged files before every commit: ignore rules are not
a guarantee against secrets in arbitrary files.

Local-first means storage and calculations remain local. Planned AI chat sends
questions and selected aggregate tool results to OpenAI. Raw backups, GPS tracks,
free-text workout notes, and the database itself will not be uploaded by the app.
Chat will disclose the data flow before use; offline reports remain available.

## Layout and plans

```text
planning/                 Architecture, milestones, and decisions
src/unified_fitness/       FitNotes ingestion, storage, CLI and summaries
tests/fixtures/            Guidance for future synthetic test data
data/                     Ignored local personal data
.env.example              Proposed environment settings
.gitignore                Python, credentials, and personal data exclusions
pyproject.toml            Packaging and pytest configuration
README.md                 Setup and project status
```

- [Architecture and proposed data model](planning/architecture.md)
- [Prioritized implementation plan](planning/implementation-plan.md)
- [Decisions, trade-offs, and open questions](planning/decisions.md)
- [FitNotes discovery](planning/fitnotes-discovery.md)
- [Implementation handoff](planning/handoff.md)
- [Ready-to-paste next-session prompt](planning/next-session-prompt.md)

Next milestone: validate a Strava export before adding running ingestion.
