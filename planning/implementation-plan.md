# Implementation plan

Status: Both importers, SQLite v2, separate summaries, and the combined offline
weekly report are implemented and verified. The one-tool AI console is
implemented and verified with a fake client. Final MVP acceptance is pending.

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
| Implemented | Interactive AI console | The weekly tool, request limits, privacy boundary, and error handling passed synthetic verification. Live SDK and model behavior remain unverified. |
| Outstanding | Final MVP acceptance | Review the complete local workflow and run a live smoke check only with separate authorization. |

Reviewed baseline: 3404908. FitNotes passed its [milestone review](handoff.md#milestone-review).
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

## Next slice: one-tool AI console

The combined report already provides validated dates, a fixed reporting
timezone, read-only queries, aggregate metrics, and coverage. Reuse it directly
from one allowlisted tool. Both importers and schema v2 are ready for this
integration. FitNotes load semantics and real cross-export ID stability remain
unverified and do not block aggregate questions. Final end-to-end MVP
acceptance follows this slice.

### Scope and acceptance criteria

- Add a chat subcommand that uses the existing global database option.
  Handle independent questions in an interactive loop and exit cleanly on
  EOF or an explicit quit. No persisted transcript or cross-question memory.
- Use the official Python SDK and Responses API in llm.py. Make the SDK an
  optional extra and load it only for chat. Read OPENAI_API_KEY and
  OPENAI_MODEL from the environment, with a local .env fallback for chat.
  Require an explicitly configured model
  that the account can use with function calling. Report missing setup
  locally before making requests. Imports and offline reports continue
  without an SDK, key, or network.
- Expose only get_weekly_summary with two required ISO date strings and a
  strict schema. Validate the JSON shape and values locally and reuse the
  analytics date rules. Missing or ambiguous dates prompt clarification.
  The database path comes from CLI configuration. Return the result against
  the matching call ID. [OpenAI Docs on function calling](https://developers.openai.com/api/docs/guides/function-calling)
- Disclose remote processing before the first question. Send only the
  question and aggregate evidence needed for the answer. Exclude file paths,
  source IDs, exercise names, notes, tracks, credentials, and audit records.
  Request store=false without promising zero provider retention. Keep each
  question's state in memory only.
- Bound the first version to one successful tool call and at most two
  Responses requests per question. Set explicit request timeout, retries,
  question size, serialized result size, and output token limits. Unexpected
  tool names, malformed requests, extra calls, API failures, and incomplete
  responses terminate that question with a bounded message.
- Show deterministic evidence separately from model commentary. A data
  answer requires a successful tool result. Empty windows and missing
  metrics should be explained as limits of recorded data. Out-of-scope
  questions receive a short scope explanation or clarification.
- Harden the aggregate boundary before connecting it. A synthetic probe
  reproduced a divide-by-zero when a tiny positive Strava distance
  underflows during conversion to kilometers. Large finite metric values
  can sum to infinity. Make these cases fail with a bounded diagnostic or
  produce a documented unavailable value. Never send nonfinite JSON to
  the provider. Ordinary export totals and coverage must stay unchanged.

### Dependencies and essential tests

The next implementation needs the optional OpenAI SDK. A live smoke check
also needs network access, a project API key, and an account-accessible
tool-capable model. Default tests use a fake client and synthetic SQLite.
No new schema, source export, or timezone dependency is needed.

- Verify valid tool arguments dispatch to the existing weekly report and
  the outgoing aggregate equals the offline report for the same dates.
  Check call ID pairing and that the configured database remains unchanged.
- Test no-tool clarification, empty results, missing metrics, malformed JSON,
  wrong types, extra fields, unsupported tools, invalid or oversized ranges,
  and surplus calls. Confirm these paths never expose raw data.
- Test timeout, rate limit, authentication, incomplete output, and exhausted
  budgets using fake responses. Verify offline CLI commands run without the
  optional SDK and that credentials and provider error bodies stay private.
- Add regression cases for nonfinite totals and unrepresentable pace.
  Inspect fake request payloads for the data boundary and storage setting.
  An explicitly authorized live smoke check should use invented data first
  and compare displayed evidence with the offline report.

### Deferred and handover

Defer additional tools, streaming, conversation history, web or file access,
agents, caching, dashboards, and coaching. Keep the existing ingestion and
analytics limits. The [handover](ai-console-handoff.md) records the original
implementation brief. Model access and response quality remain unverified.

### Console verification

- The Windows venv suite passed 72 tests with
  `.\.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp-ai-full`.
  An earlier sandboxed run stopped at the existing hard-link test because
  Windows denied link creation. The full rerun outside the sandbox passed.
  After review, the suite passed all 72 tests again with
  `.\.venv\Scripts\python.exe -m pytest -q --basetemp data/pytest-ai-review`.
- Synthetic fixtures verified offline/tool parity, read-only database access,
  the call ID pair and outgoing payload, independent questions, invalid and
  surplus calls, unavailable metrics, size limits, and bounded API errors.
  Regression tests cover kilometer conversion underflow, nonfinite pace, and
  aggregate overflow. Unrepresentable metrics are null and retain input counts.
- The installed CLI returned 0 for `--help`, `chat --help`, and a valid
  synthetic `weekly-summary`. A reversed range, missing chat configuration,
  and a missing SDK each returned 1 with a bounded diagnostic. The installed
  venv did not contain the optional SDK. No live API request was made.
- Questions that produce no tool call get a local scope and date prompt.
  Empty windows display deterministic evidence and end locally. For other
  valid results, the second request replays the matching call and any
  provider reasoning items in their original order with `store=false` and
  tool use disabled. The SDK transport disables redirects and retries.
  See [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
  and [API data controls](https://developers.openai.com/api/docs/guides/your-data).

## Planned follow-up: conversational chat

Allow direct replies to general questions, focused clarification when more
information is needed, and specific explanations when recorded data or tool
coverage is insufficient. Keep deterministic evidence separate from model
commentary. Claims about recorded training require tool evidence.

- Start with the existing weekly summary tool. Resolve supported relative
  ranges locally in Asia/Singapore and display the dates used. Keep the tool's
  explicit date arguments, inclusive range, and 366-day limit.
- Carry a pending question across a clarification turn in memory. Clear it
  when resolved or superseded. Keep transcripts out of persistent storage and
  send only the context needed to answer.
- Preserve the existing tool allowlist and per-question request limits.
  Consider more analytical tools after the conversational behavior is verified.
- Test direct replies without database reads, relative dates at calendar
  boundaries, clarification and context clearing, and distinct responses for
  empty windows, missing metrics, and unsupported analyses.

This follow-up is design only. The current console still uses the one-tool
behavior documented above.

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
