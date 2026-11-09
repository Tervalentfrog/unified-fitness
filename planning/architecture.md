# Proposed architecture

Status: proposal for review, 2026-11-09. No application code or DDL implemented.

## Scope and boundaries

One user, one account per source, one local SQLite database, one synchronous Python
process. Keep the requested Python/SQLite/pytest stack. Use standard-library
`argparse`, `sqlite3`, `csv`, `datetime`, and small dataclasses where useful.
Avoid an ORM, web server, dataframe dependency, plugin framework, and agent framework.

Planned modules inside `src/unified_fitness/` (create only with working features):

| Module | Responsibility |
| --- | --- |
| `cli.py` | Parse commands, display reports, run the interactive console |
| `ingestion/fitnotes.py`, `ingestion/strava.py` | Validate formats and map source records |
| `db.py` | Connection setup, versioned schema, transactions, parameterized writes |
| `analytics.py` | Fixed read-only queries and deterministic metric calculations |
| `llm.py` | OpenAI calls, tool schemas, allowlisted dispatch, bounded chat loop |

Flow: local file -> source adapter -> validated records -> SQLite -> analytical
functions -> CLI report or tool result -> optional AI explanation.

Adapters expose the same small callable contract: `import_file(path, connection,
options) -> ImportReport`. Report inserted, updated, unchanged, rejected, and
unsupported counts plus bounded diagnostics (row/source ID and reason, not full
personal records). A shared report type is sufficient; no abstract base class or
dynamic plugin registry. Source adapters own mapping; persistence owns writes.

## Proposed relational model

Internal primary keys are integers; source identifiers are TEXT to preserve their
exact representation. `source` is a stable namespace (`fitnotes` or `strava`).
Source fields below are canonical requirements, not claims about export columns.

| Table | Proposed columns and constraints |
| --- | --- |
| `imports` | `id` PK, `source`, `file_sha256`, `imported_at_utc`, `adapter_version`, `options_json`, outcome counts; one row per committed attempt |
| `running_activities` | `id` PK, `source`, `source_record_id`, `activity_date`, nullable `started_at_raw`, `started_at_utc`, `timezone_name`, `distance_m`, `moving_time_s`, `elapsed_time_s`, `elevation_gain_m`; `last_import_id` FK; UNIQUE (`source`, `source_record_id`) |
| `exercises` | `id` PK, `source`, `source_exercise_id`, `name`; UNIQUE (`source`, `source_exercise_id`) |
| `strength_sets` | `id` PK, `source`, `source_record_id`, `exercise_id` FK, `performed_on`, nullable `repetitions`, `load_kg`, `source_load`, `source_load_unit`, `load_kind`, `set_order`; `last_import_id` FK; UNIQUE (`source`, `source_record_id`) |

Foreign keys enabled on every connection. Required identifiers and calendar dates
are NOT NULL. Validate finite, nonnegative distance/duration/load values and integer
repetitions; encode stable rules with CHECK constraints once source semantics are
confirmed. Unknown is NULL, never a fabricated zero. Start with date and exercise/date
indexes only where the first reports need them. Use `PRAGMA user_version` and explicit
schema changes; do not silently rebuild an existing database on version mismatch.

No universal activity table or strength session table initially. Sets retain their
source IDs, exercise identity, and date; this supports progression and training-day
counts without guessing session boundaries. If FitNotes exposes reliable session
IDs needed for a question, revisit the model after inspection. Report training days
as days, not workout sessions. Cross-source frequency uses distinct dates (a day
with both a run and lifting counts once).

## Ingestion, identity, and normalization

- Open FitNotes read-only. Check the SQLite header, integrity, `sqlite_master`,
  table/column metadata, keys, joins, schema version, unit settings, and date formats
  before defining mappings. No source table names or IDs have been assumed.
- Inspect Strava's actual CSV headers, including duplicate names, delimiters,
  encoding, sport values, identifiers, date conventions, and unit representations.
  Support validated running categories only; count excluded sports. Let the user
  extract the official archive; ZIP handling and original activity parsing are deferred.
- Prefer stable source keys for repeatable imports. Never deduplicate sets by
  exercise/date/weight/reps: identical sets can be legitimate. If stable IDs are
  absent, stop and agree on a tested identity policy before implementing that source.
- Same IDs and payloads are unchanged; changed payloads update existing rows. A file
  hash records provenance, not record identity, and does not automatically skip an
  import (adapter fixes may need reprocessing). No deletion when an ID disappears.
  Without reliable source modification times, the most recently imported values
  win, even from an older export; report updates and document this limitation.
- Preflight format errors cause no writes. Reject malformed required fields or
  ambiguous identities with reasons. Missing optional fields become NULL; malformed
  optional values become NULL with warnings only when the core record remains valid.
  Commit all accepted records and the import report in one transaction; unexpected
  errors roll back the entire attempt. Failed attempts print diagnostics, not a
  misleading successful audit row. Conflicting duplicate IDs in one file fail preflight.
- Normalize distance to meters, time to seconds, load to kilograms. Preserve raw
  load/unit and timestamp evidence where needed for ambiguous semantics. Do not infer
  units from value magnitude. Validate per-exercise unit overrides, completion flags,
  bodyweight/assisted loads, and non-strength FitNotes records before mapping them.
  Unsupported records must be counted, not silently coerced into strength sets.
- Preserve date-only FitNotes records as dates. Store UTC only when the source has an
  offset or an explicitly confirmed timezone mapping; retain raw timestamp text.
  Never fabricate midnight or label naive times UTC. Reject unresolved calendar-date
  ambiguity. Choose one reporting timezone (proposed `Asia/Singapore`) and record
  assumptions in import options; historical travel/DST semantics need validation.

## Analytics and AI boundary

Start with a deterministic running summary, training-day counts, and per-exercise
strength progression. Date ranges use inclusive ISO calendar dates; weeks start
Monday. Return range, units, source coverage, sample counts, and missing/excluded
counts alongside values. Missing history is not proof of inactivity.

Pace = summed valid moving seconds / summed corresponding distance in kilometers;
exclude zero distances and never silently substitute elapsed time. Show duration
coverage and label this aggregate pace, not an average of individual paces.
Strength progression starts with observed load/reps by exercise and comparable load
kind; volume is sum(load_kg * reps) only for records with known compatible external
loads. Do not interpret unknown load as bodyweight or mix assistance with lifted load.
Estimated 1RM and causal conclusions are deferred.

The proposed OpenAI Responses API integration uses strict JSON function schemas and
an allowlist of analytical functions. The application validates dates, bounds, and
exercise IDs and runs fixed parameterized queries over a read-only connection.
There is no SQL, arbitrary file, shell, or write tool. Strict schemas constrain
arguments; they do not establish correctness of answers. See the official
[function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling).

Bound tool rounds, result sizes, timeouts, and retries. Return clear errors for
unsupported questions or insufficient data. Require tool evidence for numeric
claims and separate measured facts from interpretations and optional suggestions.
Treat exercise names and other source strings as data, never instructions.

Send questions and necessary aggregates only. Do not upload originals, GPS routes,
or free-text workout notes. Disclose remote processing when chat starts. Use
`store=false` where supported, without promising zero provider retention; verify
provider data handling when implementing chat. Do not persist chats by default.
Tests use fake API responses; live API calls are explicit and optional.
