# Architecture and data model

Unified Fitness runs as a synchronous Python CLI for one user, with one
account per source and one local SQLite database.

| Module | Responsibility |
| --- | --- |
| `cli.py` | Parse commands and display reports |
| `ingestion/fitnotes.py`, `ingestion/strava.py` | Validate exports, map source records, and coordinate imports |
| `db.py` | Manage connections, schema versions, transactions, and SQL writes |
| `analytics.py` | Read stored data and calculate reports |
| `llm.py` | Validate and dispatch chat tool calls and manage OpenAI requests |

## Import lifecycle

[View the diagram in the README](../README.md#what-happens-during-an-import).

Preflight checks include source format and source/destination path collisions.
Accepted records and their audit entry commit together. The five mutually
exclusive row outcomes are inserted, updated, unchanged, rejected, and
unsupported. Warnings are separate. FitNotes counts refer to set rows.
See the [FitNotes contract](fitnotes-discovery.md) and
[Strava contract](strava-discovery.md) for format and validation details.

| Source record | Stored identity | Reporting date | Preserved evidence |
| --- | --- | --- | --- |
| FitNotes set | `training_log._id` | Recorded date | Raw load, unit code, and completion and pending flags |
| FitNotes exercise | `exercise._id` | N/A | Name, type code, and weight unit code |
| Strava run | `Activity ID` | Singapore date derived from the supported timestamp format | Raw start text and UTC instant |

An unchanged repeat leaves domain rows and their provenance intact and appends
an audit entry. A changed payload with a matching ID updates its row. Omitted IDs
remain stored. An older export can overwrite newer values when IDs match. Real
cross-backup FitNotes ID stability still needs controlled verification.

## Relational model

[View the diagram in the README](../README.md#what-sqlite-stores).

| Table | Grain | Key or constraint |
| --- | --- | --- |
| `imports` | One committed import attempt | Integer primary key. Records file SHA-256, UTC import time, adapter version, options, and outcome counts. |
| `exercises` | One referenced source exercise | Unique `(source, source_exercise_id)`. |
| `strength_sets` | One stored source set | Unique `(source, source_record_id)`. Requires an exercise and a last-change import. |
| `running_activities` | One stored source run | Unique `(source, source_record_id)`. Requires a last-change import. |

The diagram shows selected columns. See [db.py](../src/unified_fitness/db.py)
for the full DDL. Source IDs are stored as text. Foreign keys are enabled on
every connection. A record's import pointer identifies the attempt that last
inserted or changed the record. Exercise definitions can change independently
of set payloads.

Schema v1 contains imports, exercises, and strength sets. An import creates v2
for a new database or upgrades a valid v1 database by adding running activities
within the same transaction. Read-only reports can open v1. Check
`PRAGMA user_version` to identify the schema. Incompatible schemas produce an
error.

FitNotes normalized load, unit, load kind, and set order remain NULL. A raw zero
weight carries no validated physical-load meaning. Strava distance is stored
in meters and durations in seconds. Unknown measurements use NULL. A training
day is a distinct recorded date, so a date with both running and lifting
contributes one combined training day.

## Reports and chat

[View the diagram in the README](../README.md#what-happens-when-you-use-chat).

Weeks start Monday. Report windows use inclusive calendar dates. FitNotes dates
stay as recorded and running dates use Asia/Singapore. Coverage counts describe
which stored records contributed. Import exclusions are counted at import time,
separately from report coverage.

Chat can dispatch weekly training, running trends, running records, or strength
activity. Each turn permits one successful report call. Tool dispatch uses
validated arguments and a fixed allowlist. The database, SQL execution, files,
and shell remain local. A named strength report can include the exercise name
from the question. See the [user guide](../docs/user-guide.md#use-the-optional-ai-console)
for configuration, privacy, and request limits.
