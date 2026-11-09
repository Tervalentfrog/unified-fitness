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
