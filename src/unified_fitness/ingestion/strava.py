"""Import the validated Strava bulk-export CSV layout."""

import csv
import hashlib
import io
import json
import math
import re
from contextlib import closing
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import db
from .common import ImportReport, check_destination

# The prefix distinguishes the summary km field from the detailed meters field.
HEADER_PREFIX = (
    "Activity ID", "Activity Date", "Activity Name", "Activity Type",
    "Activity Description", "Elapsed Time", "Distance", "Max Heart Rate",
    "Relative Effort", "Commute", "Activity Private Note", "Activity Gear",
    "Filename", "Athlete Weight", "Bike Weight", "Elapsed Time", "Moving Time", "Distance",
)
MAPPED_NAMES = {"Activity ID", "Activity Date", "Activity Type", "Distance", "Elapsed Time", "Moving Time"}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
ACTIVITY_DATE = re.compile(r"([A-Za-z]{3}) ([0-9]{1,2}), ([0-9]{4}), ([0-9]{1,2}):([0-9]{2}):([0-9]{2}) (AM|PM)")
ACTIVITY_ID = re.compile(r"[1-9][0-9]*")
REPORTING_ZONE = "Asia/Singapore"


def parse_utc(value):
    match = ACTIVITY_DATE.fullmatch(value)
    if not match:
        raise ValueError
    month, day, year, hour, minute, second, period = match.groups()
    hour = int(hour)
    if not 1 <= hour <= 12:
        raise ValueError
    return datetime(int(year), MONTHS.index(month) + 1, int(day),
                    hour % 12 + 12 * (period == "PM"), int(minute), int(second),
                    tzinfo=timezone.utc)


def metric(value):
    if not value.strip():
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError
    return number


def read_runs(content, reporting_zone, report):
    reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
    header = next(reader, [])
    if (tuple(header[:len(HEADER_PREFIX)]) != HEADER_PREFIX
            or MAPPED_NAMES.intersection(header[len(HEADER_PREFIX):])
            or header.count("Elevation Gain") > 1):
        raise db.FitnessError("Unsupported Strava CSV layout. Use the validated bulk-export activities.csv.")
    elevation_index = header.index("Elevation Gain") if "Elevation Gain" in header else None
    seen = set()
    runs = []
    for row in reader:
        source_id = row[0] if row else ""
        if ACTIVITY_ID.fullmatch(source_id):
            if source_id in seen:
                raise db.FitnessError("Ambiguous Strava CSV. Duplicate activity IDs.")
            seen.add(source_id)
        if len(row) != len(header) or source_id not in seen or not row[3].strip():
            report.counts["rejected"] += 1
            report.diagnostics["invalid row width, activity ID or activity type"] += 1
            continue
        if row[3] != "Run":
            report.counts["unsupported"] += 1
            report.diagnostics["activity type outside the supported running scope"] += 1
            continue
        try:
            started = parse_utc(row[1])
            activity_date = started.astimezone(reporting_zone).date().isoformat()
            elapsed, moving, distance = map(metric, row[15:18])
            elevation = metric(row[elevation_index]) if elevation_index is not None else None
            if moving is not None and elapsed is not None and moving > elapsed:
                raise ValueError
        except (ValueError, OverflowError):
            report.counts["rejected"] += 1
            report.diagnostics["invalid activity date or metrics"] += 1
            continue
        runs.append((source_id, (activity_date, row[1], started.isoformat(),
                                 distance, moving, elapsed, elevation)))
    return runs, elevation_index is not None


def import_file(source_path, destination_path):
    source_path = source_path.resolve()
    destination_path = destination_path.resolve()
    check_destination(source_path, destination_path)
    report = ImportReport()
    try:
        reporting_zone = ZoneInfo(REPORTING_ZONE)
    except ZoneInfoNotFoundError as error:
        raise db.FitnessError("Asia/Singapore timezone data is unavailable. Install IANA timezone data or tzdata.") from error
    try:
        content = source_path.read_bytes()
        runs, has_elevation = read_runs(content, reporting_zone, report)
    except (OSError, UnicodeError, csv.Error) as error:
        raise db.FitnessError("Cannot read the Strava export. Check the path and UTF-8 CSV format.") from error

    options = json.dumps({
        "reporting_timezone": REPORTING_ZONE,
        "activity_date_interpretation": "UTC",
        "layout": "bulk_export_detailed_v1",
    }, sort_keys=True)
    check_destination(source_path, destination_path)
    with closing(db.connect(destination_path, "rwc")) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        db.check_schema(connection, initialize=True)
        import_id = db.start_import(connection, "strava", hashlib.sha256(content).hexdigest(), 1, options)
        for source_id, values in runs:
            outcome = db.save_run(connection, source_id, values, import_id, has_elevation=has_elevation)
            report.counts[outcome] += 1
        db.finish_import(connection, import_id, report.counts)
    return report
