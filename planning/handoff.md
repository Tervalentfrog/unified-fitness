# Implementation handoff

Prepared 2026-11-09. Start here, then read the linked source documents. No application
functionality was implemented during handoff preparation.

## Objective and scope

Unified Fitness is a single-user, local-first fitness history application: FitNotes
strength records and later Strava running exports -> SQLite -> deterministic
analytics -> optional OpenAI tool-calling console. Keep calculations local and
testable; future AI sends questions/selected results, not raw backups.

Next milestone: FitNotes ingestion, repeatable imports, conservative normalization,
essential tests, an argparse CLI, and a small sets/reps/training-days summary.
Do not implement Strava, AI, workout sessions, web UI, sync, or weight analytics yet.

## Repository state at handoff preparation

- Baseline includes `a783e17` (discovery and accepted decisions) and `2280931`
  (repository engineering guidelines). This handoff is being committed on `main`
  for the next session; run `git status` and `git log` for current state. No push
  is part of the handoff commit.
- Code consists only of `src/unified_fitness/__init__.py`. No DDL, importer, CLI,
  reports, tests, or generated fixtures exist. Runtime dependencies are empty.
- Python >=3.11; setuptools packaging; pytest is a development extra. `py` executes
  Python 3.14.10 here despite a path-location warning; `python` is an unusable
  Windows alias. Venv/editable install/pytest have not yet been verified.
- One ignored `.fitnotes` file exists under `data/`. Recheck it read-only. Discovery
  and handoff checks found SQLite schema version 22, integrity `ok`, and unchanged
  before/after hashes. Do not require private data for automated tests.

## Source facts and architecture

The backup has 24 distinct set IDs across five dates and one referenced exercise;
the exercise catalog has 97 entries. `training_log.exercise_id` joins `exercise._id`.
There are no declared source foreign keys; joins were checked explicitly.
Dates are ISO date-only text; reps and raw weights are integers. All recorded
weight/distance/duration values are zero. Logged exercise type is `0`.

All `is_complete` values are zero with completion tracking disabled; four
`is_pending_update` values are one. The user confirmed every set in this backup
was performed. Do not drop these rows. Other backups need an explicit performed-set
assertion. Names, dates, IDs, and individual rep values are private.

Use standard-library `sqlite3`, `argparse`, and small functions/dataclasses. Planned
modules: `db.py`, `ingestion/fitnotes.py`, `cli.py`, and a small `analytics.py`.
No ORM, pandas, plugin framework, OpenAI SDK, or dotenv needed for this milestone.

Create only `imports`, `exercises`, and `strength_sets`; see
[architecture.md](architecture.md) for columns and the first-importer contract.
Use TEXT source IDs with UNIQUE `(source, source_record_id)` / exercise equivalent,
foreign keys, transactions, parameterized SQL, and explicit destination schema
versioning. Preserve source load/type/unit/flag values. Store source version,
settings, and completion policy in existing audit metadata. No full raw-data dump.

Normalize IDs, ISO dates, and integer reps. Preserve raw nonnegative load without
assuming kg/grams. Leave normalized load/unit, load kind, and order NULL. Accept
validated type `0` records with zero distance/duration; count unsupported records.
Singapore reporting dates and Monday-start weeks are agreed; date-only lifting
records retain their recorded date and need no timezone conversion.

## Files to read

| File | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Repository engineering and agent workflow instructions |
| [architecture.md](architecture.md) | Target tables, import contract, error/identity/privacy policies |
| [fitnotes-discovery.md](fitnotes-discovery.md) | Observed source schema, field mapping, flags, and evidence limits |
| [decisions.md](decisions.md) | Accepted choices, trade-offs, remaining unknowns |
| [implementation-plan.md](implementation-plan.md) | Milestones and focused validation |
| [README.md](../README.md), [pyproject.toml](../pyproject.toml) | Setup, packaging, current status; inspect code before edits |
| [.env.example](../.env.example), [.gitignore](../.gitignore) | Proposed settings and privacy exclusions; no automatic `.env` loading |
| [tests/fixtures/README.md](../tests/fixtures/README.md), [data/README.md](../data/README.md) | Synthetic-only test policy and private file handling |

## Limitations and decisions still requiring evidence

- Weight/distance scaling, unit-code meanings, unused exercise types, and pending
  flag meaning are unknown. No nonzero or timed examples validate conversions.
  These block those features, not raw-preserving reps-only ingestion.
- Real IDs across edits/reorders/restores are unverified. Implement and test
  same-ID upserts using synthetic snapshots; do not claim real cross-backup
  stability. A source comparison is needed before extending that guarantee.
- No source modification timestamp: last imported values win under the stable-ID
  assumption, so an older export can overwrite values. Missing IDs never delete rows.
- Repeated imports may add audit rows, but must leave exercises/sets unchanged.
  Counts describe stored records, not proven complete training history.
- Reject incompatible source/destination schemas and same-file source/destination
  paths before writes. Do not silently reset databases or infer completion from flags.

## Original implementation steps

1. Read repo instructions/status/docs/code; verify Python, create `.venv`, and install
   `.[dev]`. Inspect the private backup read-only without dumping personal records.
2. Build small invented schema-v22 fixtures in pytest temporary directories; implement
   persistence and the bounded importer together. Require an explicit option such
   as `--assume-performed`, already authorized for the inspected backup.
3. Add an installed `unified-fitness` CLI with import and summary commands, a database
   path option, clear errors/exit statuses, and bounded import diagnostics.
4. Run tests and CLI smoke checks; optionally import the real backup into an ignored
   local destination twice, showing only aggregate verification. Update docs with
   actual commands, results, limitations, and deviations. Stop at this milestone.

## Acceptance criteria

- Clean installation and documented CLI help/import/summary work without API keys.
- Valid fixture data imports only referenced exercises; dates/IDs/reps and raw
  codes/flags round-trip correctly; unverified normalized fields stay NULL.
- First real-file smoke import (if the unchanged backup is present): 24 inserted
  sets, one exercise, five recorded days; repeat: 24 unchanged sets, zero updates
  or inserts. Repetition totals match local SQL without publishing private values.
- Legitimate identical sets with different IDs survive. Synthetic same-ID changes
  update once, subsequent repeats are unchanged, and omitted IDs are not deleted.
- Every examined set is counted once as inserted/updated/unchanged/rejected/unsupported;
  warnings are separate. Audit rows are atomic with accepted writes; unchanged sets
  retain last-change provenance. Fatal failures roll back the attempt.
- Focused tests cover malformed dates/types/reps, orphan references, unknown schemas,
  unsupported types/metrics, raw load and flag preservation, incomplete updates,
  transactions, empty input, summary correctness, CLI behavior, and source/destination
  path collision. Fatal preflight errors do not alter existing destination contents.
- Source hashes remain unchanged. Tests use invented data only; no exports, keys,
  personal records, or real-file-derived fixtures enter Git. Tests pass with actual
  commands/results reported; unrun checks or remaining source assumptions are explicit.


## Milestone verification

Completed on 2026-11-09 with Python 3.14.10 and pytest 9.2.0.

- `py -m venv .venv` created the environment but its first pip bootstrap failed
  in the sandbox. `.\.venv\Scripts\python.exe -m ensurepip --upgrade --default-pip`
  succeeded with normal Windows permissions. A reinstall with
  `--no-build-isolation` failed because setuptools was unavailable in the venv.
  The standard `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` succeeded
  with its isolated build and registered the CLI.
- `.\.venv\Scripts\python.exe -m pytest` initially could not create the sandbox
  temporary directory. An ignored workspace-local base temp allowed 24 tests
  to pass, with the hard-link test blocked by the sandbox. The final standard
  command under normal Windows permissions passed all 26 tests.
- The installed `.\.venv\Scripts\unified-fitness.exe --help` returned 0.
  Using the commands in [README](../README.md) with a fresh ignored database,
  the private backup imported 24 sets, then reported 24 unchanged sets on
  repeat. Both imports and summary returned 0. Summary reported one exercise
  and five days. Repetitions matched source and destination SQL. The audit
  contained two attempts and sets retained their original last-change
  provenance. Zero completion flags and four pending flags were preserved.
  The source SHA-256 was unchanged.
- Every import requires the performed-set assertion. Missing mapped fields
  fail preflight. Missing or invalid optional settings produce a warning and
  empty settings metadata. Fatal attempts roll back. Rejected and unsupported
  rows are reported by aggregate reason. Exit code 3 indicates a committed
  import with exclusions.
- Weight scaling, unit codes, flag semantics, and real ID stability across
  edits, reorders, and restores remain unverified. Synthetic updates verify
  destination behavior. When IDs match, the latest imported valid payload
  wins, including payloads from older snapshots.


## Milestone review

The focused review found no critical defects requiring code changes. The
Windows venv pytest command passed all 26 tests with normal filesystem
permissions. A fresh ignored database imported 24 sets from the confirmed
backup and returned 24 unchanged on repeat. Both database integrity checks
returned ok, and the destination foreign-key check found no violations.
The destination contained the three expected tables at schema version 1.

Local row comparisons verified canonical text IDs, recorded dates, repetitions,
raw load values and storage classes, exercise codes, and both flags. All
unverified normalized fields remained NULL. The exercise and set rows matched
before and after the repeat import, including provenance. Both audit entries
recorded the source SHA-256 and performed-set assertion. The source SHA-256
remained unchanged. The CLI summary reported one exercise and five days, and
its repetition total matched source SQL.

The v1 schema check expects the app-created definitions. Source parsing assumes
a standalone export with no SQLite sidecars and holds accepted rows in memory.
These constraints fit the current local workflow. Weight scaling, code semantics,
and cross-backup ID stability remain open. The next milestone is Strava source
validation followed by running ingestion once the export contract is verified.
