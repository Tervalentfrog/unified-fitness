# Implementation plan

Status: initialization complete; implementation awaits review. Each milestone should
leave a small working increment. Do not implement all source adapters before proving
one complete import -> database -> deterministic report workflow.

| Priority | Milestone | Completion evidence |
| --- | --- | --- |
| 0 | Planning and scaffold (this change) | Empty repository inspected; packaging, exclusions, documentation, and Git initialized; no app functionality |
| 1 | Validate source contracts | Inspect actual FitNotes backup read-only; inspect Strava CSV if available; document tables/keys, units, dates, supported records and identity policy; hand-author synthetic fixture specification |
| 2 | First offline vertical slice: FitNotes | Minimal schema + FitNotes adapter + CLI import + one per-exercise report; repeated import unchanged; edited source record updates once; real backup remains unchanged |
| 3 | Add Strava running | CSV adapter + running summary; validated units/dates and moving vs elapsed time; duplicate and overlapping export imports stable |
| 4 | Shared deterministic analytics | Weekly training days across sources, running trends and strength progression; explicit coverage, missing-data behavior, and reproducible calculations |
| 5 | Interactive AI console | OpenAI SDK + strict tool schemas + bounded loop; answers backed by metrics; offline commands work without a key; API and tool failures handled |
| 6 | MVP review and acceptance | Repeat complete workflow with local exports; review privacy, mapping accuracy, error messages, and documentation; record limitations and unresolved defects |

If FitNotes data is unavailable but Strava CSV is available, swap milestones 2 and 3
after validating that source. Do not invent a FitNotes schema to keep coding.

## Focused validation

- Milestone 1: verify source files without modifying them; record schema and format
  facts only in tracked notes. Keep real rows, paths revealing identity, and exports
  under ignored `data/`. Reconstruct tiny synthetic fixtures rather than anonymizing
  a full private backup.
- Milestone 2: use pytest temporary databases for duplicate legitimate sets, repeat
  imports, changed IDs' payloads, missing fields, mixed units, unsupported schemas,
  incomplete sets, foreign keys, and transaction rollback on unexpected failure.
  Assert exact counts and known normalized values; compare source hashes before/after.
- Milestone 3: test quoted CSV fields, duplicate headers, numeric/date errors, unknown
  units, unrelated sports, overlapping exports, zero distance, and missing moving time.
- Milestone 4: hand-calculated expected metrics; empty database, inclusive boundaries,
  week/year transitions, timezone offsets, date-only lifting records, same-day overlap,
  incomplete coverage, and incompatible load kinds. No network required.
- Milestone 5: fake API responses cover unknown tools, invalid arguments, multiple
  tool calls, empty results, exhaustion of limits, rate limits and authentication
  errors. Check answer evidence and measured/interpretive separation against a short
  fixed question set. No real credentials or paid calls in the default test suite.
- Milestone 6: compare local source totals with imported/unsupported/rejected counts;
  repeat imports and verify stable analytical totals. Review staged files for private
  data and document all known gaps. Run only relevant checks until final acceptance.

## Immediate next task and prerequisites

Review the proposed architecture, then select a usable Python 3.11+ interpreter and
inspect a local `.fitnotes` backup. Discover its real schema, stable row identity,
unit overrides, completion semantics, and date precision. Write a short mapping
note and synthetic fixture specification before writing importer code.

Needed before the relevant milestone: a FitNotes backup, a Strava personal export
CSV, confirmation of reporting timezone/unit ambiguities, and later an API key plus
an account-accessible tool-capable model. None is needed to review this scaffold.

## Initialization verification

No existing files, Git metadata, or applicable parent `AGENTS.md` were found.
The environment's `python` command failed through the Windows App Execution Alias;
the `py` launcher was absent. Python packaging/import checks and pytest could not
be run. There are deliberately no placeholder tests or application entry points.
Validate installation once a real interpreter is available, then add tests with
the first functional slice.

Filesystem checks confirmed all ten scaffold files exist, local Markdown links
resolve, and no trailing whitespace was found. Git ignore checks covered personal
data, database sidecars, environment files, and synthetic CSV exceptions. Git is
initialized on `main`, with no files staged and no commits created.
