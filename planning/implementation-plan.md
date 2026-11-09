# Implementation plan

Status: FitNotes ingestion and reporting are implemented and verified. Each milestone should
leave a small working increment. Do not implement all source adapters before proving
one complete import -> database -> deterministic report workflow.

FitNotes discovery is documented in [fitnotes-discovery.md](fitnotes-discovery.md).
Its schema and current records are inspected, but weight/unit encodings and ID
stability across backups remain unverified. The accepted first report is sets,
reps, and recorded training days; load-based progression waits for unit validation.
[Strava discovery](strava-discovery.md) is complete for the inspected export.
The running importer and schema migration are pending.

| Priority | Milestone | Completion evidence |
| --- | --- | --- |
| 0 | Planning and scaffold (this change) | Empty repository inspected; packaging, exclusions, documentation, and Git initialized; no app functionality |
| 1 | Validate source contracts | Inspect actual FitNotes backup read-only; inspect Strava CSV if available; document tables/keys, units, dates, supported records and identity policy; hand-author synthetic fixture specification |
| 2 | First offline vertical slice: FitNotes | Three tables (`imports`, `exercises`, `strength_sets`) + adapter + CLI import + set/repetition/day summary; repeat imports leave domain rows unchanged; synthetic same-ID updates tested with real cross-backup stability explicitly unverified; source backup unchanged |
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
  imports, changed IDs' payloads, missing fields, unsupported types/metrics/schemas,
  completion policy, raw flag preservation, foreign keys, and transaction rollback.
  Verify the confirmed backup's zero completion flags do not discard performed sets;
  preserve raw zero loads without claiming known kilograms, bodyweight, or set order.
  Verify missing columns and malformed updates cannot silently erase valid values.
  Assert exact set/repetition/day counts; compare source hashes before/after.
  Add mixed-unit and normalized-load tests when those mappings are validated.
- Milestone 3: test quoted CSV fields, duplicate headers, numeric/date errors, unknown
  units, unrelated sports, overlapping exports, zero distance, and missing moving time.
- Milestone 4: hand-calculated expected metrics; empty database, inclusive boundaries,
  week/year transitions, timezone offsets, date-only lifting records, same-day overlap,
  incomplete coverage, and incompatible load kinds. No network required.
  Reject reporting-timezone changes on an existing imported database; keep import
  rejection totals distinct from date-filtered analytical exclusions.
- Milestone 5: fake API responses cover unknown tools, invalid arguments, multiple
  tool calls, empty results, exhaustion of limits, rate limits and authentication
  errors. Check answer evidence and measured/interpretive separation against a short
  fixed question set. No real credentials or paid calls in the default test suite.
- Milestone 6: compare local source totals with imported/unsupported/rejected counts;
  repeat imports and verify stable analytical totals. Review staged files for private
  data and document all known gaps. Run only relevant checks until final acceptance.

## Immediate next task and prerequisites

The FitNotes slice passed the [milestone review](handoff.md#milestone-review).
Next, review the [Strava source contract](strava-discovery.md), then implement
its CSV importer, v1-to-v2 migration, and running summary. Confirm FitNotes weight encoding before implementing load-based reports
and validate real ID behavior before promising updates across edited backups.

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
