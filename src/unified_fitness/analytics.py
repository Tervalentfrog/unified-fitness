"""Deterministic summaries of stored training records."""

from contextlib import closing
from datetime import date, timedelta

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

    return summarize_runs(rows)


def summarize_runs(rows):
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


def report_dates(start, end):
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise db.FitnessError("Use valid YYYY-MM-DD dates for --from and --to.") from None
    if (first.isoformat(), last.isoformat()) != (start, end):
        raise db.FitnessError("Use valid YYYY-MM-DD dates for --from and --to.")
    if last < first:
        raise db.FitnessError("--to must be on or after --from.")
    if (last - first).days >= 366:
        raise db.FitnessError("Choose a range of at most 366 days.")
    return first, last


def monday(day):
    return day - timedelta(days=day.weekday())


def observed_bounds(rows):
    # Both queries order by recorded date, and the bounds describe this window only.
    return {"first": rows[0][0], "last": rows[-1][0]} if rows else None


def weekly_summary(path, start, end):
    first, last = report_dates(start, end)
    with closing(db.connect(path, "ro")) as connection, connection:
        connection.execute("BEGIN")
        version = db.check_schema(connection)
        sets = connection.execute(
            """SELECT performed_on, repetitions FROM strength_sets
               WHERE performed_on BETWEEN ? AND ? ORDER BY performed_on, id""",
            (start, end),
        ).fetchall()
        runs = [] if version == 1 else connection.execute(
            """SELECT activity_date, distance_m, moving_time_s, elapsed_time_s, elevation_gain_m
               FROM running_activities WHERE activity_date BETWEEN ? AND ?
               ORDER BY activity_date, source, source_record_id""",
            (start, end),
        ).fetchall()

    first_week = monday(first)
    weeks = {
        first_week + timedelta(days=offset): ([], [])
        for offset in range(0, (last - first_week).days + 1, 7)
    }
    for row in sets:
        weeks[monday(date.fromisoformat(row[0]))][0].append(row)
    for row in runs:
        weeks[monday(date.fromisoformat(row[0]))][1].append(row)

    summaries = []
    for week, (week_sets, week_runs) in weeks.items():
        strength_days = {day for day, _ in week_sets}
        running_days = {row[0] for row in week_runs}
        repetitions = [reps for _, reps in week_sets if reps is not None]
        summaries.append({
            "week_start": week.isoformat(),
            "recorded_training_days": len(strength_days | running_days),
            "strength": {
                "recorded_strength_days": len(strength_days),
                "sets": len(week_sets),
                "repetitions": sum(repetitions) if repetitions else None,
                "sets_with_repetitions": len(repetitions),
            },
            "running": summarize_runs(week_runs),
        })
    return {
        "from": start,
        "to": end,
        "reporting_timezone": "Asia/Singapore",
        "observed_dates": {"strength": observed_bounds(sets), "running": observed_bounds(runs)},
        "weeks": summaries,
    }
