# Strava export discovery

Inspected locally on 2026-11-09. This is a source contract proposal for one
account export. The implemented import contract and verification are recorded below.

## Inventory

The extracted archive contains 38 CSV files, one JSON file, and four
directories. The top-level activities.csv is UTF-8 without a BOM, comma
delimited, and uses CSV quoting. All 287 records have the same 104 fields as
the header. Activity Date contains commas inside quoted fields. The activity
directory has 287 GPX files. Every CSV Filename resolves to a distinct file
there. The routes directory has four separate GPX files. Clubs and media
contain no files. The other account files, including profile data, are outside
the running import scope. No private paths, IDs, record values, or coordinates
are included in this document.

The activity types are 270 Run, 13 Hike, and 4 Walk. Activity ID is a
positive canonical decimal string and unique in all 287 rows. There are no
identical full rows. Keep identity based on the ID even when two activities
share metrics. One snapshot provides no evidence about ID continuity after
deletion and re-upload.

## CSV contract and mapping

Column positions are one-based evidence for this export. A parser should
validate a recognized header layout and use positional CSV reading or explicit
occurrence indexes. A bare DictReader would silently overwrite repeated names.
Five names repeat twice: Elapsed Time, Distance, Max Heart Rate, Relative
Effort, and Commute. Reject missing or ambiguous required columns. Extra
unmapped columns can be ignored when the recognized layout stays unambiguous.

| Source column | Meaning and observed format | Proposed use |
| --- | --- | --- |
| 1 Activity ID | Positive decimal text | source_record_id as TEXT, with source set to strava |
| 2 Activity Date | English abbreviated month and 12-hour clock with seconds, no offset | Keep in started_at_raw. Parse with explicit English month and AM/PM handling independent of process locale. Use the corroborated UTC policy below. |
| 4 Activity Type | Text | Accept exact Run in the first slice. Count Hike, Walk, and other recognized non-run rows as unsupported. |
| 7 and 18 Distance | First is lower-precision km. Second is detailed meters. | Map column 18 to distance_m. Never mix the two implicitly. |
| 6 and 16 Elapsed Time | Integer text and decimal-form seconds respectively. Values agree on all rows. | Map column 16 to elapsed_time_s. |
| 17 Moving Time | Decimal-form seconds | Map to moving_time_s. Keep distinct from elapsed time. |
| 21 Elevation Gain | Decimal-form ascent in meters | Map to elevation_gain_m. Zero stays zero. |
| 19 Max Speed and 20 Average Speed | Decimal-form speed, consistent with m/s for available averages | Defer storage. Derive moving pace from distance and moving time. |
| 8 and 31 Max Heart Rate, 32 Average Heart Rate | Optional decimal-form bpm | Defer. First maximum is more populated. Both maxima agree where both exist. |
| 13 Filename, 46 Start Time | Relative activity file link. Start Time is blank in every row. | Filename used only for discovery. Import uses Activity Date. |

The API reference documents metric units for analogous activity fields. It
does not specify this CSV header layout. The following local comparisons
support the mapping for the inspected layout. [Strava API reference](https://developers.strava.com/docs/reference/#api-models-DetailedActivity)

- All distances agree within 10 m after converting the first Distance column
  from km. The first value is lower in 259 rows, so avoid assuming nearest
  rounding. A simple great-circle sum of GPX point distances was within 10%
  of the detailed CSV distance for 285 of 287 activities. Use Strava's summary
  distance, since a point sum can differ with sampling or processing.
- Every detailed elapsed and moving value is whole seconds represented as
  decimal text. The GPX first-to-last point span was within five seconds of
  elapsed time for 285 activities. All 287 rows have positive distance and
  both durations, with moving time at most elapsed time. Moving time is
  strictly shorter for 245 runs.
- Average speed is present for 217 runs and agrees within 0.1 m/s with
  detailed distance divided by moving time wherever supplied. The planned
  aggregate pace is sum of moving seconds divided by corresponding kilometers,
  over rows with positive distance and moving time. Track coverage. Race pace
  shown in Strava may use elapsed time. [Strava moving time and pace](https://support.strava.com/en-us/articles/15401804-moving-time-speed-and-pace-calculations)
- Elevation gain is present and nonnegative throughout, including 72 runs with
  recorded zero. The CSV and API naming support treating it as reported ascent
  in meters. No independent elevation calibration was performed.
- Average heart rate and the first maximum are each present for 43 runs. The
  second maximum is present for 21. Elevation loss, speed, grade-adjusted
  metrics, and other sensor fields have gaps. Missing values remain unknown.

## Timestamp policy

Every Activity Date matched both the linked GPX metadata timestamp and its
first offset-aware trackpoint timestamp when interpreted as UTC. That is
strong evidence for UTC in this export. It does not establish the convention
for every bulk-export variant, especially exports without linked tracks.
Record the UTC interpretation in import options for the validated input
contract. Require an explicit source policy for other naive formats. Do not
infer the timestamp from the machine timezone or use an activity's GPS location
as its timezone.

Store the canonical UTC instant in started_at_utc and derive activity_date
by converting it to the fixed reporting timezone Asia/Singapore. This changes
the calendar date for 10 runs in this export. Leave timezone_name NULL if it
represents the activity's original timezone. Record the reporting timezone in
audit metadata and retain Monday-start reporting weeks. The Windows venv
raised ZoneInfoNotFoundError for Asia/Singapore. Ensure IANA zone data is
available in the next milestone, for example via tzdata where the system
database is absent. Fail clearly if unavailable.

## Destination and importer

Schema v2 adds running_activities to the three v1 tables. Import transactions
create v2 for new databases and upgrade valid v1 databases in place, preserving
the FitNotes and audit rows. Read-only summaries also support v1 databases.

Use UNIQUE (source, source_record_id) and last_import_id as a foreign key to
imports. Reuse the current connection and import audit helpers. Keep CSV
validation and normalization in a small source-specific adapter. Upsert by
source ID, keep unchanged rows and their provenance untouched, and retain
records absent from later exports. Reject ambiguous duplicate IDs in one file.
Hash the CSV for audit provenance and commit audit counts with domain writes.
Only a valid supplied field should update stored evidence. Keep supported blank
optional metrics NULL and preserve prior values when an optional column is
absent. Validate finite nonnegative numerics and flag invalid duration
relationships. Exercise these cases with invented CSV fixtures and a synthetic
v1 database.

## MVP boundary

activities.csv alone is sufficient for run counts, training dates, distance,
moving and elapsed time, reported ascent, and calculated moving pace under the
validated contract. GPX was corroborating evidence during discovery. Routine
imports need no activity-file parsing. Route visualization, GPS splits,
heart-rate streams, speed and grade-adjusted pace, cadence, power, weather,
gear, personal text, and non-running activities are deferred. The inspected
export does not establish other layouts, locale formats, or manual activity
semantics. [Strava bulk export and GPX documentation](https://support.strava.com/hc/en-us/articles/216918437-Exporting-your-Data-and-Bulk-Export)

## Verification and Git exclusions

Used the local Python venv with csv, Decimal, datetime, and ElementTree for
aggregate inspection. The CSV SHA-256 matched before and after the read.
Application tests were outside the discovery-only pass. Implementation tests are recorded below.

Git status, the staged diff, and git ls-files showed no private exports,
databases, or credentials staged or tracked. The only tracked data/ entry is
the generic usage README. The tracked .env.example is the configuration
template. git check-ignore verified the actual Strava export and FitNotes
backup, nested export paths, SQLite artifacts, environment files, and key
patterns. Synthetic CSV and TSV fixture paths remain eligible for tracking.
Ignore rules protect ordinary Git adds. A forced add or sensitive content
under an unrecognized name still requires staged-diff review.


## Implementation verification

- .\.venv\Scripts\python.exe -m pip install -e ".[dev]" installed the editable
  package and tzdata on Windows. The system timezone database is used where
  available.
- .\.venv\Scripts\python.exe -m pytest passed 40 tests, including migration
  rollback, quoted fields, duplicate headers and IDs, time and metric
  validation, overlapping imports, optional ascent, and pace coverage.
- The installed import-strava and running-summary commands verified the
  actual CSV against a fresh ignored copy of the v1 FitNotes smoke database.
  The first import inserted 270 runs. The repeat reported 270 unchanged.
  Each counted 17 unsupported activities and zero rejected rows, so both
  returned the documented exit code 3.
- The database reached version 2. Existing FitNotes rows, provenance, audit
  entries, and summary stayed identical. Running rows and summary stayed
  identical on repeat. Distance, moving and elapsed seconds, and ascent
  totals matched CSV aggregation. Integrity and foreign-key checks passed.
  The source CSV SHA-256 stayed unchanged.
- The importer recognizes the inspected header prefix through the detailed
  Distance column, with optional Elevation Gain and unmapped trailing fields.
  An absent elevation column preserves previously stored ascent. Explicit
  blanks represent unknown values. The UTC interpretation is limited to this
  validated layout and is recorded in audit metadata.
