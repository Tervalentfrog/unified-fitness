# Unified Fitness

A local-first, single-user application for importing FitNotes strength history and
Strava running history into SQLite, then querying measured trends from a console.

**Status:** FitNotes v22 and Strava imports, offline summaries, and an optional one-tool AI console are implemented.

## Development setup

Use Python 3.11 or newer. From the repository root in PowerShell:

~~~
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
~~~

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python`.
Imports and summaries run offline. On Windows, the package installs tzdata
for Singapore reporting dates. Other platforms can use system IANA timezone data.

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

## Import and summarize runs

Use the extracted activities.csv from the validated Strava bulk-export layout.
Replace the example CSV path below with the local path under data/.

~~~powershell
.\.venv\Scripts\unified-fitness.exe --db data/fitness.sqlite3 import-strava data/strava-export/activities.csv
.\.venv\Scripts\unified-fitness.exe --db data/fitness.sqlite3 running-summary
~~~

A successful import transaction upgrades an existing v1 database to v2 and
preserves its FitNotes data and audit history. The strength summary remains
available as summary. The Strava importer accepts Run rows and counts other
activity types as unsupported. Exit code 3 means the import committed with
exclusions, including non-running activities.

The running summary reports run count, distinct Singapore running days, known
distance, moving and elapsed seconds, reported ascent, and moving pace in
seconds per kilometer. Coverage counts show which runs contributed. Pace
uses total moving time divided by corresponding distance for runs with both
values positive. Empty metrics, unrepresentable totals, and unavailable pace are
JSON null. Coverage counts still reflect records with the relevant inputs.

See the [Strava source contract and verification](planning/strava-discovery.md)
for the CSV layout, timezone policy, and repeat-import results.

## Report weekly training

Point the command at the database used for both imports.

~~~powershell
.\.venv\Scripts\unified-fitness.exe --db data/fitness.sqlite3 weekly-summary --from 2024-01-01 --to 2024-02-29
~~~

The date range is inclusive and limited to 366 days. The JSON report includes
every Monday-start week intersecting that range, even weeks with no stored
records. FitNotes dates stay as recorded and runs use Singapore reporting
dates. A date with both sources counts as one combined training day.
Each week includes separate strength and running totals with coverage counts.
Unknown metrics are null. The report reads both sources in one snapshot and
can read a v1 database as strength-only.

## Ask about weekly training

Install the optional SDK. Put `OPENAI_API_KEY` and `OPENAI_MODEL` in a local
`.env` file in the directory where you launch chat. Use one UTF-8
`NAME=value` line per setting. Existing process environment values take
precedence, even when blank. Choose a Responses API model your account can
use with function calling.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ai]"
.\.venv\Scripts\unified-fitness.exe chat
~~~

Chat uses `data/unified-fitness.sqlite3` by default. Pass `--db` before
`chat` to select another database. Reporting uses Asia/Singapore.

Ask a self-contained question such as “How many runs and strength sets were
recorded each week from 2024-01-01 through 2024-01-28?” Include both dates
in every question. Type `/quit` or send EOF to exit.

Chat sends the question and the read-only weekly report for the selected date
range to OpenAI for remote processing. Keep private details out of questions.
The report contains aggregate evidence and coverage. The database, its path,
source IDs, exercise names, workout notes, and GPS tracks stay local.
Chat requests `store=false`. Provider retention depends on applicable data
controls. [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data)

Chat displays deterministic evidence separately from model commentary and
reports empty windows locally. Each question allows one successful tool call
and up to two requests. The limits are 2,000 question characters, 32 KiB of
serialized evidence, and 1,024 output tokens per request, with a 30-second
SDK timeout, zero retries, and redirects disabled. Chat keeps no transcript or cross-question
history. Imports and offline reports require neither the SDK nor credentials.

The Windows venv pytest suite passed all 72 tests with a fake API client and
invented data. Installed CLI checks covered help, a synthetic weekly report,
an invalid date range, and chat setup errors. Live SDK and model behavior
remain unverified. See the [console verification](planning/implementation-plan.md#console-verification).

## Local data and credentials

Store private exports and databases under `data/`. Keep credentials, raw data,
personal reports, and transcripts out of Git. Only synthetic test fixtures belong
in `tests/fixtures/`. Review staged files before every commit: ignore rules are not
a guarantee against secrets in arbitrary files.

## Layout and plans

```text
planning/                 Architecture, milestones, and decisions
src/unified_fitness/       FitNotes and Strava ingestion, storage, CLI and summaries
tests/fixtures/            Guidance for future synthetic test data
data/                     Ignored local personal data
.env.example              Environment settings reference
.gitignore                Python, credentials, and personal data exclusions
pyproject.toml            Packaging and pytest configuration
README.md                 Setup and project status
```

- [Architecture and proposed data model](planning/architecture.md)
- [Prioritized implementation plan](planning/implementation-plan.md)
- [Decisions, trade-offs, and open questions](planning/decisions.md)
- [FitNotes discovery](planning/fitnotes-discovery.md)
- [FitNotes implementation handoff](planning/handoff.md)
- [Historical FitNotes implementation prompt](planning/next-session-prompt.md)
- [Strava discovery and verification](planning/strava-discovery.md)
