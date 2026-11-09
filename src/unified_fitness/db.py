"""Versioned SQLite storage for the consolidated database."""

import sqlite3
from datetime import datetime, timezone

SCHEMA_V1 = (
    """CREATE TABLE imports (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        file_sha256 TEXT NOT NULL,
        imported_at_utc TEXT NOT NULL,
        adapter_version INTEGER NOT NULL,
        options_json TEXT NOT NULL,
        inserted INTEGER NOT NULL DEFAULT 0,
        updated INTEGER NOT NULL DEFAULT 0,
        unchanged INTEGER NOT NULL DEFAULT 0,
        rejected INTEGER NOT NULL DEFAULT 0,
        unsupported INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE exercises (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_exercise_id TEXT NOT NULL,
        name TEXT NOT NULL,
        source_type_id INTEGER,
        source_weight_unit_id INTEGER,
        UNIQUE (source, source_exercise_id)
    )""",
    """CREATE TABLE strength_sets (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        exercise_id INTEGER NOT NULL REFERENCES exercises(id),
        performed_on TEXT NOT NULL,
        repetitions INTEGER CHECK (repetitions >= 0),
        load_kg REAL,
        source_load BLOB CHECK (source_load >= 0),
        source_load_unit TEXT,
        load_kind TEXT,
        set_order INTEGER,
        source_unit_code INTEGER,
        source_is_complete INTEGER,
        source_is_pending_update INTEGER,
        last_import_id INTEGER NOT NULL REFERENCES imports(id),
        UNIQUE (source, source_record_id)
    )""",
)
RUNNING_SCHEMA = """CREATE TABLE running_activities (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        activity_date TEXT NOT NULL,
        started_at_raw TEXT,
        started_at_utc TEXT,
        timezone_name TEXT,
        distance_m REAL CHECK (distance_m >= 0),
        moving_time_s REAL CHECK (moving_time_s >= 0),
        elapsed_time_s REAL CHECK (elapsed_time_s >= 0),
        elevation_gain_m REAL CHECK (elevation_gain_m >= 0),
        last_import_id INTEGER NOT NULL REFERENCES imports(id),
        UNIQUE (source, source_record_id)
    )"""
SCHEMA_V2 = (*SCHEMA_V1, RUNNING_SCHEMA)


class FitnessError(Exception):
    """An actionable error safe to display without private input values."""


def connect(path, mode):
    connection = sqlite3.connect(path.resolve().as_uri() + f"?mode={mode}", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def check_schema(connection, *, initialize=False):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    objects = {
        sql for (sql,) in connection.execute(
            "SELECT sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    if version == 0 and not objects and initialize:
        for statement in SCHEMA_V2:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 2")
        return 2
    if version == 1 and objects == set(SCHEMA_V1):
        if initialize:
            connection.execute(RUNNING_SCHEMA)
            connection.execute("PRAGMA user_version = 2")
            return 2
        return 1
    if version != 2 or objects != set(SCHEMA_V2):
        raise FitnessError("Incompatible destination schema. Use a Unified Fitness database or a new path.")
    return 2


def save_run(connection, source_id, values, import_id, *, has_elevation):
    existing = connection.execute(
        """SELECT activity_date, started_at_raw, started_at_utc, distance_m,
                  moving_time_s, elapsed_time_s, elevation_gain_m
           FROM running_activities WHERE source = 'strava' AND source_record_id = ?""",
        (source_id,),
    ).fetchone()
    if existing is None:
        connection.execute(
            """INSERT INTO running_activities
               (source, source_record_id, activity_date, started_at_raw, started_at_utc,
                distance_m, moving_time_s, elapsed_time_s, elevation_gain_m, last_import_id)
               VALUES ('strava', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_id, *values, import_id),
        )
        return "inserted"
    if not has_elevation:
        values = (*values[:-1], existing[-1])
    if existing == values:
        return "unchanged"
    connection.execute(
        """UPDATE running_activities SET activity_date = ?, started_at_raw = ?,
           started_at_utc = ?, distance_m = ?, moving_time_s = ?, elapsed_time_s = ?,
           elevation_gain_m = ?, last_import_id = ?
           WHERE source = 'strava' AND source_record_id = ?""",
        (*values, import_id, source_id),
    )
    return "updated"


def start_import(connection, source, file_hash, adapter_version, options_json):
    return connection.execute(
        """INSERT INTO imports (source, file_sha256, imported_at_utc, adapter_version, options_json)
           VALUES (?, ?, ?, ?, ?)""",
        (source, file_hash, datetime.now(timezone.utc).isoformat(), adapter_version, options_json),
    ).lastrowid


def finish_import(connection, import_id, counts):
    connection.execute(
        """UPDATE imports SET inserted = :inserted, updated = :updated,
           unchanged = :unchanged, rejected = :rejected, unsupported = :unsupported
           WHERE id = :import_id""",
        {**counts, "import_id": import_id},
    )


def save_exercise(connection, source, source_id, values):
    connection.execute(
        """INSERT INTO exercises (source, source_exercise_id, name, source_type_id, source_weight_unit_id)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (source, source_exercise_id) DO UPDATE SET
               name = excluded.name, source_type_id = excluded.source_type_id,
               source_weight_unit_id = excluded.source_weight_unit_id
           WHERE (name, source_type_id, source_weight_unit_id) IS NOT
                 (excluded.name, excluded.source_type_id, excluded.source_weight_unit_id)""",
        (source, source_id, *values),
    )
    return connection.execute(
        "SELECT id FROM exercises WHERE source = ? AND source_exercise_id = ?",
        (source, source_id),
    ).fetchone()[0]


def save_set(connection, source, source_id, exercise_id, values, import_id):
    existing = connection.execute(
        """SELECT exercise_id, performed_on, repetitions, source_load, source_unit_code,
                  source_is_complete, source_is_pending_update
           FROM strength_sets WHERE source = ? AND source_record_id = ?""",
        (source, source_id),
    ).fetchone()
    payload = (exercise_id, *values)
    if existing is None:
        connection.execute(
            """INSERT INTO strength_sets
               (exercise_id, performed_on, repetitions, source_load, source_unit_code,
                source_is_complete, source_is_pending_update, last_import_id, source, source_record_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*payload, import_id, source, source_id),
        )
        return "inserted"
    # SQLite integer and real storage classes are distinct raw evidence.
    if existing == payload and type(existing[3]) is type(payload[3]):
        return "unchanged"
    connection.execute(
        """UPDATE strength_sets SET exercise_id = ?, performed_on = ?, repetitions = ?,
           source_load = ?, source_unit_code = ?, source_is_complete = ?,
           source_is_pending_update = ?, last_import_id = ?
           WHERE source = ? AND source_record_id = ?""",
        (*payload, import_id, source, source_id),
    )
    return "updated"
