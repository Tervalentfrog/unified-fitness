# Implementation plan

Status: Both importers, SQLite v2, separate summaries, and the combined offline
weekly report are implemented and verified. The AI console remains pending.

FitNotes discovery is documented in [fitnotes-discovery.md](fitnotes-discovery.md).
Its schema and current records are inspected, but weight/unit encodings and ID
stability across backups remain unverified. The accepted first report is sets,
reps, and recorded training days; load-based progression waits for unit validation.
[Strava discovery](strava-discovery.md) is complete for the inspected export.
The running importer, v1-to-v2 migration, and running summary are implemented
and verified against that export.

| Priority | Milestone | Completion evidence |
| --- | --- | --- |
| 0 | Planning and scaffold (this change) | Empty repository inspected; packaging, exclusions, documentation, and Git initialized; no app functionality |
| 1 | Validate source contracts | Inspect actual FitNotes backup read-only; inspect Strava CSV if available; document tables/keys, units, dates, supported records and identity policy; hand-author synthetic fixture specification |
| 2 | First offline vertical slice: FitNotes | Three tables (`imports`, `exercises`, `strength_sets`) + adapter + CLI import + set/repetition/day summary; repeat imports leave domain rows unchanged; synthetic same-ID updates tested with real cross-backup stability explicitly unverified; source backup unchanged |
| 3 | Add Strava running | CSV adapter + running summary; validated units/dates and moving vs elapsed time; duplicate and overlapping export imports stable |
| 4 | Shared deterministic analytics | A date-bounded weekly report across both sources, with distinct training days, running totals, strength sets and repetitions, and explicit coverage |
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
  imports, changed IDs' payloads, missing fields, unsupported types/metrics/schemas,
  completion policy, raw flag preservation, foreign keys, and transaction rollback.
  Verify the confirmed backup's zero completion flags do not discard performed sets;
  preserve raw zero loads without claiming known kilograms, bodyweight, or set order.
  Verify missing columns and malformed updates cannot silently erase valid values.
  Assert exact set/repetition/day counts; compare source hashes before/after.
  Add mixed-unit and normalized-load tests when those mappings are validated.
- Milestone 3: test quoted CSV fields, duplicate headers, numeric/date errors, unknown
  units, unrelated sports, overlapping exports, zero distance, and missing moving time.
- Milestone 4: see the [weekly report acceptance criteria and tests](#weekly-training-report).
- Milestone 5: fake API responses cover unknown tools, invalid arguments, multiple
  tool calls, empty results, exhaustion of limits, rate limits and authentication
  errors. Check answer evidence and measured/interpretive separation against a short
  fixed question set. No real credentials or paid calls in the default test suite.
- Milestone 6: compare local source totals with imported/unsupported/rejected counts;
  repeat imports and verify stable analytical totals. Review staged files for private
  data and document all known gaps. Run only relevant checks until final acceptance.

## MVP progress

| Status | Requirement | Evidence or remaining work |
| --- | --- | --- |
| Complete | Local, auditable storage and repeatable imports | FitNotes v22 and the validated Strava CSV layout write to one v2 database. Migration preserves v1 rows. Both adapters retain source identity and last-change provenance. |
| Complete | Separate offline summaries | Strength sets, reps and recorded days, plus running totals, moving pace and coverage. Existing CLI commands work without credentials. |
| Partial | Normalized fitness history | FitNotes loads, units and order remain unknown. Strava support covers the inspected layout and exact Run rows. Cross-export ID stability remains unverified. |
| Complete | Integrated weekly analytics | A bounded shared date window reports both sources and deduplicates recorded training days. |
| Outstanding | Interactive AI console and final MVP acceptance | Add a bounded, read-only console after the shared report has a verified contract. Then verify the complete local workflow and privacy boundary. |

Baseline commit: f1e4937. FitNotes passed its [milestone review](handoff.md#milestone-review).
Strava passed [verification](strava-discovery.md#implementation-verification).
The weekly report verification passed all 46 tests. See the results below.

## Weekly training report

Provide a single offline CLI command that answers how often the user trained
and how much running and strength work was recorded each week. This is the
first user-facing report that benefits from both sources being in one database.
It establishes a small, testable analytics result for the later AI console.

### Scope and acceptance criteria

- Add one read-only report in analytics.py and one CLI command, provisionally
  weekly-summary with required --from and --to ISO dates and the existing
  global --db option. Both dates are inclusive. Reject malformed or reversed
  ranges with a bounded CLI diagnostic. Limit the first version to 366 days
  to keep output bounded.
- Return the requested range, fixed Asia/Singapore reporting policy, observed
  in-range date bounds per source, and chronologically ordered Monday-start
  weeks. Emit every week intersecting the range, including empty weeks.
  Partial weeks count only records inside the requested dates.
- Use stored FitNotes performed_on and Strava activity_date. Count distinct
  dates across both sources, so lifting and running on the same date count
  as one training day. Keep separate strength and running day counts for
  context. Leave source identities and tables separate.
- Report strength set and repetition totals and run count, distance, moving
  and elapsed time, ascent, and moving pace. Reuse the existing pace and
  coverage rules. Keep unavailable sums and pace NULL and expose contributing
  counts. Empty weeks mean no stored records in the selected interval.
- Read both sources in one SQLite read transaction. Support v2 and treat a
  valid v1 database as strength-only without migrating it. Preserve the
  existing summary commands and their output contracts. Keep import-level
  rejection counts separate from the report.
- Document the command and verify it locally against both imports in one
  ignored database. Compare a selected window with independent SQL totals
  and distinct dates. Keep private values out of tracked files.

### Dependencies and essential tests

The existing schema, Python runtime, and SQLite are sufficient. Stored dates
already encode the source date policies. No migration, new package, live API
key, or new source discovery is required.

- Use invented mixed-source rows with multiple sets and runs on the same day.
  Check that combined days are deduplicated and per-source counts remain correct.
- Check inclusive endpoints, Monday and year boundaries, partial and empty
  weeks, and an imported Strava UTC instant that falls on the next Singapore date.
- Hand-check weighted pace and coverage when some runs have zero distance or
  missing moving time. Verify missing values stay distinct from recorded zero.
- Check one-source and empty databases, v1 compatibility without writes,
  invalid CLI ranges, deterministic output, and both existing summary commands.

### Deferred work

Defer normalized load and strength progression until FitNotes units are
verified. Also defer session inference, GPS and heart-rate analysis, cross-source
activity matching, dashboards, configurable timezones, and new import formats.
Keep the AI console as the following slice. One verified report is enough to
give it an initial read-only tool contract.

### Verification

The Windows venv command .\.venv\Scripts\python.exe -m pytest passed all 46
tests, including mixed-source deduplication, boundary dates, Singapore
rollover, pace coverage, v1 reads, empty weeks, and invalid ranges.

The installed CLI imported 24 FitNotes sets and 270 Strava runs into one
fresh ignored SQLite database. Over a 366-day window containing records
from both sources, independent SQL verified each week's distinct dates,
strength counts, run totals, metric coverage, and weighted moving pace.
The in-range source bounds matched SQL. Repeated reports matched, SQLite
integrity passed, and both source hashes stayed unchanged.

## Initialization verification

No existing files, Git metadata, or applicable parent `AGENTS.md` were found.
The environment's `python` command failed through the Windows App Execution Alias;
the `py` launcher was absent. Python packaging/import checks and pytest could not
be run. There are deliberately no placeholder tests or application entry points.
Validate installation once a real interpreter is available, then add tests with
the first functional slice.

Filesystem checks confirmed all ten scaffold files exist, local Markdown links
resolve, and no trailing whitespace was found. Git ignore checks covered personal
data, database sidecars, environment files, and synthetic CSV exceptions. At the
end of kickoff, Git was initialized on `main` with no staging or commits; this is
a historical verification record, not a statement about the current Git state.
