"""Deterministic summaries of stored strength records."""

from contextlib import closing

from . import db


def strength_summary(path):
    with closing(db.connect(path, "ro")) as connection, connection:
        connection.execute("BEGIN")
        db.check_schema(connection)
        # Sum repetitions in Python to avoid SQLite's signed 64-bit SUM overflow.
        by_exercise = {}
        days = set()
        for exercise_id, name, day, reps in connection.execute(
            """SELECT e.id, e.name, s.performed_on, s.repetitions
               FROM strength_sets AS s JOIN exercises AS e ON e.id = s.exercise_id
               ORDER BY e.name, e.source, e.source_exercise_id"""
        ):
            exercise = by_exercise.setdefault(
                exercise_id, {"exercise": name, "sets": 0, "repetitions": 0}
            )
            exercise["sets"] += 1
            exercise["repetitions"] += reps if reps is not None else 0
            days.add(day)
        return {
            "sets": sum(exercise["sets"] for exercise in by_exercise.values()),
            "repetitions": sum(exercise["repetitions"] for exercise in by_exercise.values()),
            "recorded_training_days": len(days),
            "exercises": list(by_exercise.values()),
        }


def running_summary(path):
    with closing(db.connect(path, "ro")) as connection, connection:
        connection.execute("BEGIN")
        version = db.check_schema(connection)
        rows = [] if version == 1 else connection.execute(
            """SELECT activity_date, distance_m, moving_time_s, elapsed_time_s, elevation_gain_m
               FROM running_activities ORDER BY source, source_record_id"""
        ).fetchall()

    pace_rows = [(distance, moving) for _, distance, moving, _, _ in rows
                 if distance and moving]
    pace = None
    if pace_rows:
        pace = sum(moving for _, moving in pace_rows) / (sum(distance for distance, _ in pace_rows) / 1000)
    result = {
        "runs": len(rows),
        "recorded_running_days": len({row[0] for row in rows}),
        "moving_pace_s_per_km": pace,
        "runs_with_pace": len(pace_rows),
    }
    for index, field in enumerate(("distance_m", "moving_time_s", "elapsed_time_s", "elevation_gain_m"), 1):
        known = [row[index] for row in rows if row[index] is not None]
        result[field] = sum(known) if known else None
        result[f"runs_with_{field}"] = len(known)
    return result
