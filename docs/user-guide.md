# User guide

## Import and summarize

Complete the [README setup](../README.md#setup) first. The examples use the
same database throughout. Run them from the repository root.

Place a standalone FitNotes SQLite v22 export in `data/`. Replace
`your-backup.fitnotes` with its filename. Use `--assume-performed` only
after confirming the sets in that export were performed.

~~~
.\.venv\Scripts\unified-fitness.exe --help
.\.venv\Scripts\unified-fitness.exe import-fitnotes data/your-backup.fitnotes --assume-performed
.\.venv\Scripts\unified-fitness.exe summary
~~~

The default database path is `data/unified-fitness.sqlite3`. To use another
database, put `--db PATH` before the subcommand on every invocation. On macOS/Linux
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
records. Stderr groups reasons and warnings.

| Exit code | What happened |
| --- | --- |
| `0` | Import committed without rejected or unsupported rows, or report completed. |
| `1` | Fatal error. Check the error before retrying. |
| `2` | Invalid command usage. Check subcommand help. |
| `3` | Import committed with exclusions. Check the counts and reasons. |

## Import and summarize runs

Use the extracted activities.csv from the validated Strava bulk-export layout.
Replace the example CSV path below with the local path under data/.

~~~powershell
.\.venv\Scripts\unified-fitness.exe import-strava data/strava-export/activities.csv
.\.venv\Scripts\unified-fitness.exe running-summary
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

See the [Strava source contract and verification](../planning/strava-discovery.md)
for the CSV layout, timezone policy, and repeat-import results.

## Report weekly training

Point the command at the database used for both imports.

~~~powershell
.\.venv\Scripts\unified-fitness.exe weekly-summary --from 2024-01-01 --to 2024-02-29
~~~

The date range is inclusive and limited to 366 days. The JSON report includes
every Monday-start week intersecting that range, even weeks with no stored
records. FitNotes dates stay as recorded and runs use Singapore reporting
dates. A date with both sources counts as one combined training day.
Each week includes separate strength and running totals with coverage counts.
Unknown metrics are null. The report reads both sources in one snapshot and
can read a v1 database as strength-only.

## Use the optional AI console

Install the optional SDK. Put `OPENAI_API_KEY` and `OPENAI_MODEL` in a local
`.env` file in the directory where you launch chat. Use one UTF-8
`NAME=value` line per setting. Existing process environment values take
precedence, even when blank. Choose a Responses API model your account can
use with function calling and Structured Outputs.

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ai]"
.\.venv\Scripts\unified-fitness.exe chat
~~~

Chat uses `data/unified-fitness.sqlite3` by default. Pass `--db` before
`chat` to select another database. Reporting uses Asia/Singapore.

Ask general questions directly or ask about recorded training, for example
“How many runs did I record last week?” Chat resolves today, yesterday,
this week, last week, this month, and last month in Asia/Singapore. Weeks
start Monday. “This week” and “this month” run through today. For other
ranges, supply both dates in YYYY-MM-DD form. If chat asks for a range,
reply with a supported phrase or a range such as `2024-01-01 to 2024-01-28`.
Type `/quit` or send EOF to exit.

Chat sends your question and relevant clarification context to OpenAI. For
questions about recorded training, it can also send one selected read-only
report. A named strength report includes the exercise name supplied in your
question. Source files, database paths, source IDs, workout notes, and GPS
tracks stay local. Chat requests `store=false`. Provider retention depends on
applicable data controls.
[OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data)

Chat displays deterministic evidence separately from model commentary and
reports empty windows locally. Chat can select weekly training, running trends,
running records, or strength activity. Each submitted turn allows one successful tool call
and up to two requests. The limits are 2,000 question characters, 32 KiB of
serialized evidence, and 1,024 output tokens per request, with a 30-second
SDK timeout, zero retries, and redirects disabled. Chat keeps pending questions and clarification context in memory. It saves no transcript. Imports
and offline reports require neither the SDK nor credentials.

## Compare running trends

The default comparison uses the latest four completed Singapore calendar
weeks and the preceding four. Choose an explicit historical range if recent
history is sparse. A comparison with explicit dates uses the immediately
preceding window of equal length.

~~~powershell
.\.venv\Scripts\unified-fitness.exe running-trends
.\.venv\Scripts\unified-fitness.exe running-trends --mode comparison --from 2024-02-01 --to 2024-02-29
.\.venv\Scripts\unified-fitness.exe running-trends --mode range --from 2024-01-01 --to 2024-02-29
.\.venv\Scripts\unified-fitness.exe running-trends --mode year --year 2024
.\.venv\Scripts\unified-fitness.exe running-trends --mode yearly
.\.venv\Scripts\unified-fitness.exe running-trends --mode all_time
~~~

The report shows recorded runs, distinct running days, known distance and
distance-weighted moving pace. Pace changes compare runs in the same distance
band and require three eligible runs per band on each side. Lower seconds
per kilometer means a faster recorded pace. Route, terrain, and effort
remain unaccounted for.

`range` shows weekly buckets, `year` shows monthly buckets, and `yearly`
shows up to 12 calendar years ending at the latest recorded year. Partial
periods are labelled. `all_time` includes older stored history even when
the yearly view omits it.

In chat, try “Is my running pace improving?”, “Show my running history by
year”, or “What is my all-time running distance?” Chat can use one report
per turn and displays its local evidence before model commentary.

## Check running records and patterns

~~~powershell
.\.venv\Scripts\unified-fitness.exe running-records fastest_pace --distance-band 5_to_under_10_km
.\.venv\Scripts\unified-fitness.exe running-records weekday
.\.venv\Scripts\unified-fitness.exe running-records time_of_day --mode year --year 2024
~~~

Fastest pace uses the whole run's average moving pace and reports ties.
Choose `under_5_km`, `5_to_under_10_km`, or `10_km_or_more`. Time of day
counts recorded UTC starts in six-hour Singapore clock buckets. Weekday
uses stored Singapore reporting dates. Both report ties and coverage.
Reports default to all recorded history. Use `--mode year --year YYYY`
or `--mode range --from YYYY-MM-DD --to YYYY-MM-DD` to narrow the scope.

In chat, try “What was my fastest moving pace for runs 5 to under 10 km?”
or “Which weekday do I run most often?” A broad running-period question
can prompt for weekday or time of day. Exact-distance finish times,
splits, and seasonal patterns remain deferred.

## Review strength activity

Use the full exercise name shown by `summary`. Names match case-insensitively
after trimming whitespace. If more than one stored exercise has that name,
the report returns an ambiguity status. Omit `--exercise` for overall totals.

~~~powershell
.\.venv\Scripts\unified-fitness.exe summary
.\.venv\Scripts\unified-fitness.exe strength-activity --mode all_time --exercise "Your exercise name"
.\.venv\Scripts\unified-fitness.exe strength-activity --mode year --year 2024
~~~

Strength activity uses the same period modes as running trends. It reports
sets, known repetitions, and distinct recorded training dates. Reps are a
subtotal when coverage is incomplete. In chat, try “How many sets of
Barbell Bench Press did I record in 2024?” using the name in your own
summary. For one named exercise, the report can also summarize verified
external loads in kilograms. It shows max recorded load, kg × reps volume,
and an Epley estimate from sets of 2–10 reps. The estimate assumes an effort
level that FitNotes does not record and should be treated as approximate.
Volume is a subtotal when eligible set coverage is incomplete.

The current FitNotes importer preserves raw weights and leaves normalized
load fields empty. Load metrics therefore remain unavailable for existing
imports pending [validation of the source encoding](../planning/implementation-plan.md#load-based-strength-progression-slice).

## Local data and credentials

Store private exports and databases under `data/`. Keep credentials, raw data,
personal reports, and transcripts out of Git. Only synthetic test fixtures belong
in `tests/fixtures/`. Review staged files before every commit: ignore rules are not
a guarantee against secrets in arbitrary files.

## Read the evidence

| What you see | How to read it |
| --- | --- |
| `null` metric | The metric is unavailable. Check coverage for usable inputs. |
| Zero recorded runs or sets | No matching records are stored for the period. |
| Partial period | The bucket covers only part of a calendar week, month, or year. |
| Training day | One distinct recorded date. Lifting and running on the same date count as one combined day. |

For example, a 5 km run in 25 minutes and a 10 km run in 60 minutes contribute
85 minutes over 15 km. The aggregate moving pace is 340 seconds per kilometer
(5:40/km). A third run with missing moving time still counts as a run and is
excluded from the pace calculation.
