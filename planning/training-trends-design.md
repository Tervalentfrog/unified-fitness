# Training trends design

Running trends and strength activity support yearly breakdowns and all-time
totals. Load-based progression, running records, and start-time patterns
remain deferred.

## Source evidence

A read-only check of the current v2 database found positive distance and
moving time and a stored UTC start on every imported run. All stored
strength sets have known reps. None has a normalized load or a known load kind.
These checks establish field coverage in the current database. Export
coverage, recording consistency, and cross-export ID stability have
separate limits documented in the source notes.

Strava supports recorded distance, frequency, and moving pace. Route,
effort, terrain, weather, and activity mix can affect comparisons. FitNotes
supports exercise-specific set and rep counts and recorded training days.
Raw zero weights have unknown semantics. The existing backup cannot
establish max load, estimated 1RM, or load-based volume.

## Shared period contract

Both proposed tools use a strict schema with required keys. Nullable keys
take JSON null when unused. Unknown keys and invalid combinations are rejected
locally. All dates are inclusive. Use the Asia/Singapore calendar and
Monday-start weeks. FitNotes dates remain as recorded.

| Argument | Type | Rule |
| --- | --- | --- |
| `mode` | enum | `comparison`, `range`, `year`, `yearly`, or `all_time` |
| `start`, `end` | ISO date or null | Both required in `range`. Both optional together in `comparison`. Null in other modes. |
| `year` | integer or null | Required only in `year`. Use calendar years. |

- **Comparison** defaults to the latest four completed Singapore calendar
  weeks versus the four immediately preceding weeks. With explicit dates,
  compare that window with the immediately preceding window of equal length.
  Keep each window at most 366 days. Validate both ranges and underflow at
  the supported calendar boundary. If recent data is sparse or stale,
  disclose that and invite an explicit historical range. Never silently
  move the comparison to the last recorded date.
- **Range** returns totals and up to 54 Monday-start buckets over at most
  366 days. First and last buckets can be partial and are labelled as such.
- **Year** returns the requested year's totals and up to 12 calendar-month
  buckets. Future years are invalid. For the current year, stop at the
  Singapore reporting date and mark the year and current month as partial.
- **Yearly** returns the latest 12 calendar years ending at the latest
  eligible recorded year, including empty intervening years. State when
  earlier years were omitted. Mark the current year and any known clipped
  periods. Return totals by year without automatically comparing a partial
  year to a full year. A matched year-to-date comparison can come later.
- **All time** returns one aggregate over all eligible recorded rows through
  the reporting date, with observed bounds and no implied comparison.
  An all-time trend request uses yearly buckets. All-time totals and
  individual calendar-year requests still cover history older than the
  yearly output cap.

An empty period means zero stored activities or sets. Unknown metrics stay
null. Include observed bounds and distinguish periods with no records from
known incomplete calendar periods. Observed bounds alone cannot establish
where export coverage begins or ends.

Each result contains `status`, `reporting_timezone`, `mode`,
`observed_dates`, `periods`, `comparison`, and `limitations`.
Each period carries inclusive bounds, a partial-period flag, and its
metrics and coverage. In comparison mode, label the periods baseline and
current and include deterministic deltas and per-metric eligibility.
Use null for unavailable values or deltas and a reason code for suppressed
comparisons. Compute absolute deltas as current minus baseline. Percent
changes, regression, and significance testing are outside this slice.

## get_running_trends

Use the shared arguments. Return recorded run count, distinct running
days, known distance in meters, moving pace in seconds per kilometer,
and contributing run counts. Include matched distance-band comparisons
when a comparison is requested. Use bands below 5 km, 5 to below 10 km,
and 10 km or longer.

Reuse the existing pace calculation. Sum moving seconds and divide by
the corresponding kilometers over runs with finite, positive distance
and moving time. This weights pace by distance. Report eligible count
and distance. Never substitute elapsed time or average individual paces.
Reuse finite-number guards and preserve coverage when a result is null.

Show overall pace as descriptive evidence. For a directional pace claim,
compare like distance bands and require at least three pace-eligible runs
in each period in that band. This threshold is a reporting guard, with
no claim of statistical significance. If bands disagree, report mixed
results. If none qualifies, report insufficient comparable runs.
A negative pace delta means fewer moving seconds per kilometer. Similar
distance does not control for route, intensity, or other conditions.

For distance and frequency, report recorded totals and deltas for equal
windows. Label distance as a known-distance subtotal when coverage is
incomplete and suppress its directional comparison if either period has
runs with missing distance or an unavailable total. For an empty period,
show the counts and avoid interpreting the gap as inactivity.

Supports weekly distance and frequency, year-by-year running history,
all-time totals, and questions about whether recorded pace changed over
comparable distances.

## get_strength_progress

The tool adds `exercise` (string or null) to the shared schema. Use null for overall
recorded strength activity. For a named exercise, trim whitespace and
match the full name case-insensitively using Python case folding. Match
against local exercise definitions, then filter by the single resolved
exercise ID using a bound SQL parameter. Distinct exercise IDs with the
same normalized name remain ambiguous. Return `exercise_not_found` or
`exercise_ambiguous` and request clarification. Avoid automatic aliasing,
substring matches, and merging variants such as barbell and dumbbell press.

Return the requested exercise scope, recorded set count, total known reps,
sets with known reps, and distinct recorded strength days per period.
Count multiple sets on the same date as one recorded day. Reps are a
subtotal when coverage is incomplete. Suppress directional rep deltas if
either period has incomplete rep coverage or no recorded sets. Treat set
and day counts as activity measures. Include a stable
`load_metrics_unavailable` limitation for questions about strength gains.
Reps and set counts cannot establish that a lifter got stronger.

Supports “How often did I bench press?”, “Did my squat reps change?”, and
overall or exercise-specific training frequency by range or year. “Am I
stronger at bench press?” can receive workload context and an explanation
of why max load and estimated 1RM are unavailable.

Future load analytics require controlled FitNotes exports to verify nonzero
weights, unit overrides, weight scaling, compatible load kinds, and
completion semantics. After validation, max recorded weight can compare
like exercise and load kinds, with reps shown for context. Load volume
would sum kg × reps only over compatible, verified external loads. Estimated
1RM stays deferred until a formula, rep range, and applicability rules are
reviewed. Raw weights, zero loads, bodyweight, and assistance must never be
silently treated as equivalent.

## Overall questions and useful follow-ons

Route “all-time running totals” to running `all_time` and “running trends
by year” to running `yearly`. “How has my running changed?” defaults to
`comparison`. Keep combined weekly questions on `get_weekly_summary`.
Clarify broad requests that need both sources over multiple years. The MVP
can answer one source at a time while preserving one tool call per turn.

Two small follow-ons are viable from stored Strava fields. Keep them
outside the first trends slice:

- **Fastest recorded run.** Ask whether the user means fastest average
  moving pace or shortest finish time at a specified distance. For the
  first, require a distance band or an explicitly agreed minimum distance
  to avoid crowning very short efforts. Use eligible positive distance and
  moving time, report the metric and ties, and distinguish a whole-run
  average from a split or race result. Exact-distance splits require data
  beyond the current schema. A later local record view can show identifying
  details. Any chat result should carry only the necessary computed result.
- **Most common running period.** Clarify whether the user means time of
  day, weekday, or season. For a time-of-day histogram, convert known UTC
  starts to Asia/Singapore and count fixed buckets with documented boundaries.
  Report all modal ties and timestamp coverage. Weekday can use stored
  reporting dates. Time-of-day buckets describe Singapore clock time,
  including for travel runs. No inference from date-only rows.

## Implementation and acceptance

1. In analytics.py, reuse the current run row shape and `summarize_runs`
   eligibility and numeric rules. Reuse the exercise join and Python rep
   totals. Share only the date validation and period calculations needed by
   both reports. Keep the existing weekly report contract intact.
2. Use parameterized SQLite queries over one read-only transaction per
   report. Aggregate in Python or fixed SQL. SQLite v2 needs no migration
   or new dependency. A valid v1 database has strength data only. Use the
   existing offline analytics entry points as the model for parity tests.
3. In llm.py, extend the allowlist with fixed descriptions and local
   argument checks. Describe when to use each tool and the difference
   between an explicit range, a comparison, a year, and all time. Resolve
   defaults and dates locally and check that model-selected arguments match
   the requested scope before reading. Preserve the database path in CLI
   configuration and retain one successful call and two provider requests
   per submitted turn.
4. Keep evidence separate from commentary. Send only finite, size-bounded
   aggregate JSON. Exclude raw rows, IDs, timestamps, source exercise
   labels, notes, and paths. Use the user's exercise wording or an opaque
   scope label in chat evidence. Treat user and imported text as data.
   Require numerical claims to agree with returned values and decline
   directional claims when eligibility is insufficient.

Essential tests use invented SQLite data and a fake API client:

- Verify pace with unequal distances against hand calculations and
  independent SQL input totals. Cover missing or zero inputs, overflow,
  boundary distances, changes in run mix, and opposing band trends.
- Verify equal-length windows across month/year boundaries, leap days,
  Singapore rollover, partial current periods, empty weeks and years,
  all-time totals, and the yearly output cap. Check zero baselines and
  stale or insufficient data.
- Verify per-exercise and overall sets, reps, and distinct days, including
  multiple sets on a date, missing reps, case and whitespace matching,
  unknown and duplicate names, and parameterized filtering. Check that
  unknown loads never produce max weight, volume, or estimated 1RM.
- Verify tool selection with fixed representative fake responses, local
  validation of malformed and out-of-scope calls, structured insufficient
  evidence, request and result limits, call ID pairing, read-only database
  parity, and absence of raw personal fields in provider payloads.
  Fake routing tests verify the application contract. Model selection
  quality can be evaluated separately with an authorized live test.

Keep cross-source causal analysis, race prediction, training recommendations,
GPS and split analytics, and arbitrary date grouping outside this milestone.
