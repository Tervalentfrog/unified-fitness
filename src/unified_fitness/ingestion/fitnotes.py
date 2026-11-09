"""Validate and import standalone FitNotes schema-v22 backups."""

import hashlib
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date

from .. import db

SOURCE = "fitnotes"
SOURCE_VERSION = 22
REQUIRED = {
    "exercise": ("_id", "name", "exercise_type_id", "weight_unit_id"),
    "training_log": (
        "_id", "exercise_id", "date", "reps", "metric_weight", "distance",
        "duration_seconds", "unit", "is_complete", "is_pending_update",
    ),
}
OUTCOMES = ("inserted", "updated", "unchanged", "rejected", "unsupported")
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(OUTCOMES, 0))
    diagnostics: Counter[str] = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)


def nonnegative_integer(value):
    return type(value) is int and value >= 0


def positive_id(value):
    return nonnegative_integer(value) and value > 0


def nonnegative_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def iso_date(value):
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def columns(connection, table):
    # Require real tables. Hidden/generated columns are outside the backup contract.
    return {
        name for _, name, *_ in connection.execute(f"PRAGMA table_info({table})")
    }


def read_settings(connection, tables, report):
    fields = ("metric", "mark_sets_complete")
    if "settings" in tables and set(fields) <= columns(connection, "settings"):
        rows = connection.execute("SELECT metric, mark_sets_complete FROM settings LIMIT 2").fetchall()
        if len(rows) == 1 and all(type(value) is int and value in (0, 1) for value in rows[0]):
            return dict(zip(fields, rows[0]))
    report.warnings.append("FitNotes settings were missing or invalid. Completion uses the explicit assertion.")
    return {}


def classify(row, exercises):
    source_id, exercise_id, day, reps, load, distance, duration, unit, complete, pending = row
    if not positive_id(source_id) or not positive_id(exercise_id):
        return "rejected", "invalid set or exercise identifier"
    exercise = exercises.get(exercise_id)
    if exercise is None:
        return "rejected", "missing exercise reference"
    name, type_code, weight_unit = exercise
    if not isinstance(name, str) or not name.strip() or not all(
        nonnegative_integer(code) for code in (type_code, weight_unit)
    ):
        return "rejected", "invalid exercise definition"
    if not iso_date(day) or not nonnegative_integer(reps):
        return "rejected", "invalid calendar date or repetitions"
    if not all(nonnegative_number(value) for value in (load, distance, duration)):
        return "rejected", "invalid raw metric"
    if not nonnegative_integer(unit) or any(
        type(flag) is not int or flag not in (0, 1) for flag in (complete, pending)
    ):
        return "rejected", "invalid unit code or flag"
    if type_code != 0 or distance != 0 or duration != 0:
        return "unsupported", "exercise type or distance/duration outside the supported scope"
    return None, None


def read_backup(connection, report):
    if connection.execute("PRAGMA user_version").fetchone()[0] != SOURCE_VERSION:
        raise db.FitnessError("Unsupported FitNotes schema version. Expected version 22.")
    tables = {
        name.lower() for (name,) in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table'"
        )
    }
    for table, fields in REQUIRED.items():
        if table not in tables or not set(fields) <= columns(connection, table):
            raise db.FitnessError(f"Incompatible FitNotes backup. Missing required {table} fields.")
        duplicate = connection.execute(
            f"SELECT 1 FROM {table} WHERE _id IS NOT NULL GROUP BY _id HAVING count(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate:
            raise db.FitnessError(f"Ambiguous FitNotes backup. Duplicate IDs in {table}.")

    exercises = {
        source_id: (name, type_code, unit)
        for source_id, name, type_code, unit in connection.execute(
            "SELECT _id, name, exercise_type_id, weight_unit_id FROM exercise"
        )
        if positive_id(source_id)
    }
    accepted = []
    for row in connection.execute(f"SELECT {', '.join(REQUIRED['training_log'])} FROM training_log"):
        outcome, reason = classify(row, exercises)
        if outcome:
            report.counts[outcome] += 1
            report.diagnostics[reason] += 1
        else:
            source_id, exercise_id, day, reps, load, _, _, unit, complete, pending = row
            accepted.append((str(source_id), exercise_id, (day, reps, load, unit, complete, pending)))
    return exercises, accepted, read_settings(connection, tables, report)


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_standalone(path):
    if any(path.with_name(path.name + suffix).exists() for suffix in SIDECAR_SUFFIXES):
        raise db.FitnessError("Use a standalone FitNotes export without SQLite sidecars.")


def check_destination(source, destination):
    # SQLite can write, truncate or remove destination sidecars during recovery.
    writable_paths = [destination, *(
        destination.with_name(destination.name + suffix) for suffix in SIDECAR_SUFFIXES
    )]
    if any(path == source or (path.exists() and source.samefile(path)) for path in writable_paths):
        raise db.FitnessError("Source and destination must be different files, including SQLite sidecars.")


def import_file(source_path, destination_path, *, assume_performed=False):
    if not assume_performed:
        raise db.FitnessError("Use --assume-performed only after confirming the backup contains performed sets.")
    source_path = source_path.resolve()
    destination_path = destination_path.resolve()
    check_destination(source_path, destination_path)

    report = ImportReport()
    check_standalone(source_path)
    try:
        digest = file_hash(source_path)
        # Immutable mode avoids source-side journal files. Only standalone exports qualify.
        uri = source_path.as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.execute("PRAGMA trusted_schema = OFF")
            exercises, accepted, settings = read_backup(connection, report)
        check_standalone(source_path)
        if digest != file_hash(source_path):
            raise db.FitnessError("FitNotes backup changed during import. Retry with a fixed export.")
    except (sqlite3.Error, OSError) as error:
        raise db.FitnessError("Cannot read the FitNotes backup. Check the path and SQLite export.") from error

    options = json.dumps({
        "assume_performed": True,
        "source_schema_version": SOURCE_VERSION,
        "reporting_timezone": "Asia/Singapore",
        "settings": settings,
    }, sort_keys=True)
    if accepted:
        report.warnings.append("Load encoding is unverified. Raw values retained and normalized fields left empty.")
    check_destination(source_path, destination_path)
    try:
        with closing(db.connect(destination_path, "rwc")) as connection, connection:
            # Serialize the schema check and all writes, including the audit row.
            connection.execute("BEGIN IMMEDIATE")
            db.check_schema(connection, initialize=True)
            import_id = db.start_import(connection, SOURCE, digest, 1, options)
            exercise_ids = {}
            for source_id, exercise_id, values in accepted:
                if exercise_id not in exercise_ids:
                    exercise_ids[exercise_id] = db.save_exercise(
                        connection, SOURCE, str(exercise_id), exercises[exercise_id]
                    )
                outcome = db.save_set(connection, SOURCE, source_id, exercise_ids[exercise_id], values, import_id)
                report.counts[outcome] += 1
            db.finish_import(connection, import_id, report.counts)
    except sqlite3.Error as error:
        raise db.FitnessError("Could not import into the destination. Check database access and available space.") from error
    return report
