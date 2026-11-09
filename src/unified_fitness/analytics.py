"""Deterministic summaries of stored training records."""

from contextlib import closing
from datetime import date, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db

REPORTING_ZONE = "Asia/Singapore"
PERIOD_MODES = ("comparison", "range", "year", "yearly", "all_time")
RUN_COLUMNS = "activity_date, distance_m, moving_time_s, elapsed_time_s, elevation_gain_m"
DISTANCE_BANDS = {
    "under_5_km": (0, 5000),
    "5_to_under_10_km": (5000, 10000),
    "10_km_or_more": (10000, float("inf")),
}
RECORD_METRICS = ("fastest_pace", "weekday", "time_of_day")
RECORD_MODES = ("all_time", "year", "range")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
TIME_BUCKETS = ("00:00–06:00", "06:00–12:00", "12:00–18:00", "18:00–24:00")


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
            f"""SELECT {RUN_COLUMNS}
               FROM running_activities ORDER BY source, source_record_id"""
        ).fetchall()

    return summarize_runs(rows)


def moving_pace(distance, seconds):
    kilometers = distance / 1000
    # Tiny positive distances can round to zero in kilometers.
    if kilometers > 0 and isfinite(distance) and isfinite(seconds):
        pace = seconds / kilometers
        if pace > 0 and isfinite(pace):
            return pace
    return None


def pace_metrics(rows):
    eligible = [(distance, moving) for _, distance, moving, _, _ in rows
                if distance and moving and distance > 0 and moving > 0
                and isfinite(distance) and isfinite(moving)]
    distance = sum(distance for distance, _ in eligible)
    seconds = sum(moving for _, moving in eligible)
    return {
        # Divide totals to weight pace by distance.
        "moving_pace_s_per_km": moving_pace(distance, seconds),
        "runs_with_pace": len(eligible),
        "pace_distance_m": distance if eligible and isfinite(distance) else None,
    }


def summarize_runs(rows):
    pace = pace_metrics(rows)
    del pace["pace_distance_m"]
    result = {
        "runs": len(rows),
        "recorded_running_days": len({row[0] for row in rows}),
        **pace,
    }
    for index, field in enumerate(("distance_m", "moving_time_s", "elapsed_time_s", "elevation_gain_m"), 1):
        known = [row[index] for row in rows if row[index] is not None]
        total = sum(known)
        result[field] = total if known and isfinite(total) else None
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


def read_runs(connection, version, start, end, *, include_start=False):
    if version == 1:
        return []
    columns = RUN_COLUMNS + (", started_at_utc" if include_start else "")
    return connection.execute(
        f"""SELECT {columns} FROM running_activities WHERE activity_date BETWEEN ? AND ?
            ORDER BY activity_date, source, source_record_id""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


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
        runs = read_runs(connection, version, first, last)

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
        summaries.append({
            "week_start": week.isoformat(),
            "recorded_training_days": len(strength_days | running_days),
            "strength": strength_metrics(week_sets),
            "running": summarize_runs(week_runs),
        })
    return {
        "from": start,
        "to": end,
        "reporting_timezone": "Asia/Singapore",
        "observed_dates": {"strength": observed_bounds(sets), "running": observed_bounds(runs)},
        "weeks": summaries,
    }


def reporting_today():
    try:
        return datetime.now(ZoneInfo(REPORTING_ZONE)).date()
    except ZoneInfoNotFoundError:
        raise db.FitnessError("Install Asia/Singapore timezone data to use calendar reports.") from None


def report_window(mode, start, end, year, today):
    if mode not in PERIOD_MODES or (start is None) != (end is None):
        raise db.FitnessError("Choose a report mode and supply both dates when using a range.")
    if (year is not None) != (mode == "year") or (start is not None and mode not in ("range", "comparison")):
        raise db.FitnessError("Use a year only in year mode and dates only in range or comparison mode.")
    if mode == "year":
        if type(year) is not int or not 1 <= year <= today.year:
            raise db.FitnessError("Choose a valid calendar year no later than the current year.")
        return date(year, 1, 1), min(date(year, 12, 31), today)
    if mode in ("yearly", "all_time"):
        return date.min, today
    if start is not None:
        if not isinstance(start, str) or not isinstance(end, str):
            raise db.FitnessError("Dates must be YYYY-MM-DD strings.")
        first, last = report_dates(start, end)
    elif mode == "comparison":
        first, last = monday(today) - timedelta(days=28), monday(today) - timedelta(days=1)
    else:
        raise db.FitnessError("Range mode requires start and end dates.")
    if last > today:
        raise db.FitnessError("The reporting range cannot end after today.")
    return first, last


def running_metrics(rows):
    known = [row[1] for row in rows if row[1] is not None and isfinite(row[1])]
    distance = sum(known)
    return {
        "runs": len(rows), "recorded_running_days": len({row[0] for row in rows}),
        "distance_m": distance if known and isfinite(distance) else None,
        "runs_with_distance_m": len(known),
        **pace_metrics(rows),
    }


def rows_between(rows, start, end):
    first, last = start.isoformat(), end.isoformat()
    return [row for row in rows if first <= row[0] <= last]


def running_comparison(baseline, current, baseline_rows, current_rows):
    changes = {}
    for metric in ("runs", "recorded_running_days", "distance_m"):
        reason = None
        if not baseline["runs"] or not current["runs"]:
            reason = "empty_period"
        elif metric == "distance_m" and any(
            period[metric] is None or period["runs_with_distance_m"] != period["runs"]
            for period in (baseline, current)
        ):
            reason = "incomplete_distance"
        changes[metric] = {"delta": None if reason else current[metric] - baseline[metric], "reason": reason}

    bands = []
    directions = set()
    for label, (lower, upper) in DISTANCE_BANDS.items():
        before, after = (
            pace_metrics(row for row in rows if row[1] is not None and lower <= row[1] < upper)
            for rows in (baseline_rows, current_rows)
        )
        reason = None
        delta = None
        if min(before["runs_with_pace"], after["runs_with_pace"]) < 3:
            reason = "insufficient_comparable_runs"
        elif before["moving_pace_s_per_km"] is None or after["moving_pace_s_per_km"] is None:
            reason = "unavailable_pace"
        else:
            delta = after["moving_pace_s_per_km"] - before["moving_pace_s_per_km"]
            directions.add("faster" if delta < 0 else "slower" if delta > 0 else "unchanged")
        bands.append({"band": label, "baseline": before, "current": after,
                      "delta_s_per_km": delta, "reason": reason})
    directional = directions - {"unchanged"}
    trend = "mixed" if len(directional) > 1 else next(iter(directional or directions), "insufficient")
    return {"changes": changes, "pace_bands": bands, "pace_direction": trend}


def running_trends(path, mode="comparison", start=None, end=None, year=None, *, today=None):
    today = today if today is not None else reporting_today()
    baseline_start, first, last = report_bounds(mode, start, end, year, today)
    with closing(db.connect(path, "ro")) as connection, connection:
        connection.execute("BEGIN")
        rows = read_runs(connection, db.check_schema(connection), baseline_start, last)

    result = period_report(rows, mode, baseline_start, first, last, today, running_metrics)
    if mode == "comparison":
        before, after = result["periods"]
        result["comparison"] = running_comparison(
            before, after, rows_between(rows, baseline_start, first - timedelta(days=1)),
            rows_between(rows, first, last),
        )
    return result


def validate_record_options(metric, mode, distance_band):
    if metric not in RECORD_METRICS or mode not in RECORD_MODES:
        raise db.FitnessError("Choose a running record metric and an all-time, year, or date-range scope.")
    if metric == "fastest_pace":
        if not isinstance(distance_band, str) or distance_band not in DISTANCE_BANDS:
            raise db.FitnessError("Choose a distance band: under 5 km, 5 to under 10 km, or 10 km or more.")
    elif distance_band is not None:
        raise db.FitnessError("Use a distance band only for fastest moving pace.")


def fastest_pace(rows, distance_band):
    lower, upper = DISTANCE_BANDS[distance_band]
    in_band = [row for row in rows if row[1] is not None and 0 < row[1] and lower <= row[1] < upper]
    paces = [moving_pace(distance, moving) for _, distance, moving, _, _ in in_band
             if moving is not None and moving > 0]
    eligible = [pace for pace in paces if pace is not None]
    best = min(eligible, default=None)
    return {
        "runs_in_band": len(in_band),
        "eligible_runs": len(eligible),
        "fastest_moving_pace_s_per_km": best,
        "tied_runs": eligible.count(best),
    }


def running_histogram(rows, metric):
    labels = WEEKDAYS if metric == "weekday" else TIME_BUCKETS
    counts = dict.fromkeys(labels, 0)
    if metric == "time_of_day":
        try:
            zone = ZoneInfo(REPORTING_ZONE)
        except ZoneInfoNotFoundError:
            raise db.FitnessError("Install Asia/Singapore timezone data to use time-of-day reports.") from None
    for row in rows:
        try:
            if metric == "weekday":
                index = date.fromisoformat(row[0]).weekday()
            else:
                # Only verified UTC instants contribute to the local-clock histogram.
                instant = datetime.fromisoformat(row[-1])
                if instant.utcoffset() != timedelta(0):
                    continue
                index = instant.astimezone(zone).hour // 6
        except (TypeError, ValueError, OverflowError):
            continue
        counts[labels[index]] += 1
    highest = max(counts.values())
    return {
        "eligible_runs": sum(counts.values()),
        "buckets": counts,
        "most_common": [label for label, count in counts.items() if highest and count == highest],
    }


def running_records(path, metric, mode="all_time", start=None, end=None, year=None, distance_band=None, *, today=None):
    validate_record_options(metric, mode, distance_band)
    today = today if today is not None else reporting_today()
    first, last = report_window(mode, start, end, year, today)
    with closing(db.connect(path, "ro")) as connection, connection:
        connection.execute("BEGIN")
        rows = read_runs(connection, db.check_schema(connection), first, last,
                         include_start=metric == "time_of_day")
    metrics = fastest_pace(rows, distance_band) if metric == "fastest_pace" else running_histogram(rows, metric)
    return {
        "status": "empty" if not rows else "ok" if metrics["eligible_runs"] else "unavailable",
        "reporting_timezone": REPORTING_ZONE,
        "metric": metric, "mode": mode, "distance_band": distance_band,
        "start": None if mode == "all_time" else first.isoformat(), "end": last.isoformat(),
        "runs": len(rows),
        **metrics,
    }


def report_bounds(mode, start, end, year, today):
    try:
        first, last = report_window(mode, start, end, year, today)
        baseline_start = first - (last - first + timedelta(days=1)) if mode == "comparison" else first
    except OverflowError:
        raise db.FitnessError("The comparison extends beyond the supported calendar.") from None
    return baseline_start, first, last


def period_report(rows, mode, baseline_start, first, last, today, metrics, *, status=None):
    def period(start, end, label, *, partial=False):
        return {
            "label": label, "start": start.isoformat(), "end": end.isoformat(), "partial": partial,
            **metrics(rows_between(rows, start, end)),
        }

    result = {
        "status": status or ("ok" if rows else "empty"),
        "reporting_timezone": REPORTING_ZONE,
        "mode": mode,
        "observed_dates": observed_bounds(rows),
        "periods": [],
        "comparison": None,
        "limitations": ["recorded_data_only"],
    }
    if status is not None:
        return result
    periods = result["periods"]
    if mode == "comparison":
        baseline_end = first - timedelta(days=1)
        periods.extend([period(baseline_start, baseline_end, "baseline"), period(first, last, "current")])
        bounds = result["observed_dates"]
        if not bounds or bounds["first"] >= first.isoformat() or bounds["last"] < first.isoformat():
            result["limitations"].append("empty_comparison_period")
    elif mode == "yearly":
        if rows:
            earliest, latest = int(rows[0][0][:4]), int(rows[-1][0][:4])
            first_year = max(earliest, latest - 11)
            if first_year > earliest:
                result["limitations"].append("earlier_years_omitted")
            for bucket_year in range(first_year, latest + 1):
                low, full_end = date(bucket_year, 1, 1), date(bucket_year, 12, 31)
                high = min(full_end, today)
                periods.append(period(low, high, str(bucket_year), partial=high < full_end))
    else:
        partial = mode == "year" and last < date(first.year, 12, 31)
        total_start = first
        if mode == "all_time":
            total_start = date.fromisoformat(rows[0][0]) if rows else today
        periods.append(period(total_start, last, "total", partial=partial))
        if mode == "range":
            for offset in range(0, (last - monday(first)).days + 1, 7):
                week = monday(first) + timedelta(days=offset)
                low, high = max(first, week), week + timedelta(days=min(6, (last - week).days))
                periods.append(period(low, high, week.isoformat(), partial=low != week or (high - week).days < 6))
        elif mode == "year":
            year = first.year
            for month in range(1, last.month + 1):
                low = date(year, month, 1)
                full_end = (date(year, month + 1, 1) - timedelta(days=1)
                            if month < 12 else date(year, 12, 31))
                high = min(full_end, last)
                periods.append(period(low, high, low.isoformat()[:7], partial=high < full_end))
    return result


def strength_metrics(rows):
    repetitions = [reps for _, reps in rows if reps is not None]
    return {
        "sets": len(rows),
        "repetitions": sum(repetitions) if repetitions else None,
        "sets_with_repetitions": len(repetitions),
        "recorded_strength_days": len({day for day, _ in rows}),
    }


def strength_load_metrics(rows):
    activity = strength_metrics([row[:2] for row in rows])
    eligible = [(load, reps) for _, reps, load, kind in rows
                if kind == "external" and isinstance(load, (int, float)) and isfinite(load)
                and load > 0 and type(reps) is int and reps > 0]
    volume = sum(load * reps for load, reps in eligible)
    # Epley estimates use low-rep sets. A single belongs in the observed max.
    estimates = [load * (1 + reps / 30) for load, reps in eligible if 2 <= reps <= 10]
    best_estimate = max(estimates, default=None)
    activity["load"] = {
        "eligible_sets": len(eligible),
        "estimate_sets": len(estimates),
        "max_load_kg": max((load for load, _ in eligible), default=None),
        "volume_kg_reps": volume if eligible and isfinite(volume) else None,
        "volume_is_subtotal": bool(eligible) and len(eligible) < len(rows) and isfinite(volume),
        "estimated_1rm_kg": best_estimate if best_estimate is not None and isfinite(best_estimate) else None,
    }
    return activity


def strength_load_changes(baseline, current):
    changes = {}
    for metric in ("max_load_kg", "volume_kg_reps", "estimated_1rm_kg"):
        before, after = baseline["load"][metric], current["load"][metric]
        reason = None
        if before is None or after is None:
            reason = "unavailable_load_metric"
        elif any(period["load"]["eligible_sets"] != period["sets"] for period in (baseline, current)):
            reason = "incomplete_load_coverage"
        changes[metric] = {"delta": None if reason else after - before, "reason": reason}
    return changes


def strength_activity(path, mode="comparison", start=None, end=None, year=None, exercise=None, *, today=None):
    if exercise is not None and (not isinstance(exercise, str) or not exercise.strip() or len(exercise) > 200):
        raise db.FitnessError("Supply a nonempty exercise name of at most 200 characters.")
    today = today if today is not None else reporting_today()
    baseline_start, first, last = report_bounds(mode, start, end, year, today)
    status = None
    with closing(db.connect(path, "ro")) as connection, connection:
        connection.execute("BEGIN")
        db.check_schema(connection)
        columns = "performed_on, repetitions" if exercise is None else "performed_on, repetitions, load_kg, load_kind"
        sql = f"SELECT {columns} FROM strength_sets WHERE performed_on BETWEEN ? AND ?"
        parameters = (baseline_start.isoformat(), last.isoformat())
        if exercise is not None:
            exercise = exercise.strip()
            matches = [exercise_id for exercise_id, name in connection.execute("SELECT id, name FROM exercises")
                       if name.strip().casefold() == exercise.casefold()]
            if len(matches) != 1:
                status = "exercise_ambiguous" if matches else "exercise_not_found"
            else:
                sql += " AND exercise_id = ?"
                parameters += (matches[0],)
        rows = [] if status else connection.execute(sql + " ORDER BY performed_on, id", parameters).fetchall()

    metrics = strength_metrics if exercise is None else strength_load_metrics
    result = period_report(rows, mode, baseline_start, first, last, today, metrics, status=status)
    result["exercise"] = exercise
    if exercise is None or not any(period["load"]["eligible_sets"] for period in result["periods"]):
        result["limitations"].append("load_metrics_unavailable")
    elif any(period["load"]["estimated_1rm_kg"] is not None for period in result["periods"]):
        result["limitations"].append("estimated_1rm_effort_unknown")
    if status is None and mode == "comparison":
        baseline, current = result["periods"]
        changes = {}
        for metric in ("sets", "repetitions", "recorded_strength_days"):
            reason = None
            if not baseline["sets"] or not current["sets"]:
                reason = "empty_period"
            elif metric == "repetitions" and any(
                period["sets_with_repetitions"] != period["sets"] for period in (baseline, current)
            ):
                reason = "incomplete_repetitions"
            changes[metric] = {"delta": None if reason else current[metric] - baseline[metric], "reason": reason}
        result["comparison"] = {"changes": changes}
        if exercise is not None:
            result["comparison"]["load_changes"] = strength_load_changes(baseline, current)
    return result
