import csv
import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from unified_fitness import db
from unified_fitness.analytics import running_summary, strength_summary, weekly_summary
from unified_fitness.cli import main
from unified_fitness.ingestion import strava

HEADER = (
    "Activity ID", "Activity Date", "Activity Name", "Activity Type",
    "Activity Description", "Elapsed Time", "Distance", "Max Heart Rate",
    "Relative Effort", "Commute", "Activity Private Note", "Activity Gear",
    "Filename", "Athlete Weight", "Bike Weight", "Elapsed Time", "Moving Time",
    "Distance", "Max Speed", "Average Speed", "Elevation Gain",
)
RUN = ("123", "Feb 29, 2024, 4:00:00 PM", 'Invented, "run"', "Run", "", "700", "2.49",
       "", "", "", "", "", "", "", "", "700.0", "600.0", "2499.5", "", "", "24.5")


def row_with(row=RUN, **changes):
    row = list(row)
    for name, value in changes.items():
        row[{"id": 0, "date": 1, "sport": 3, "elapsed": 15,
             "moving": 16, "distance": 17, "elevation": 20}[name]] = value
    return row


def write_csv(path, rows, header=HEADER):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def query(path, sql):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def make_v1(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        for ddl in db.SCHEMA_V1:
            connection.execute(ddl)
        connection.execute("PRAGMA user_version = 1")
        connection.execute("""INSERT INTO imports
            (source, file_sha256, imported_at_utc, adapter_version, options_json, inserted)
            VALUES ('fitnotes', 'invented', '2024-01-01T00:00:00+00:00', 1, '{}', 1)""")
        connection.execute("INSERT INTO exercises VALUES (1, 'fitnotes', '1', 'Invented Press', 0, 0)")
        connection.execute("""INSERT INTO strength_sets
            (source, source_record_id, exercise_id, performed_on, repetitions, last_import_id)
            VALUES ('fitnotes', '123', 1, '2024-01-01', 7, 1)""")


def test_migration_mapping_and_repeat_import(tmp_path):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    write_csv(source, [RUN, row_with(id="124"), row_with(id="125", sport="Walk")])
    before = source.read_bytes()
    make_v1(dest)
    tables = ("imports", "exercises", "strength_sets")
    original_rows = [query(dest, f"SELECT * FROM {table} WHERE id = 1") for table in tables]
    assert running_summary(dest)["runs"] == 0
    assert query(dest, "PRAGMA user_version") == [(1,)]
    first = strava.import_file(source, dest)
    assert first.counts == dict(inserted=2, updated=0, unchanged=0, rejected=0, unsupported=1)
    assert query(dest, "PRAGMA user_version") == [(2,)]
    assert query(dest, "PRAGMA foreign_key_check") == []
    assert [query(dest, f"SELECT * FROM {table} WHERE id = 1") for table in tables] == original_rows
    assert strength_summary(dest)["repetitions"] == 7
    saved = query(dest, "SELECT * FROM running_activities ORDER BY id")
    assert saved[0][1:] == ("strava", "123", "2024-03-01", RUN[1], "2024-02-29T16:00:00+00:00",
                           None, 2499.5, 600, 700, 24.5, 2)
    assert strava.import_file(source, dest).counts["unchanged"] == 2
    assert query(dest, "SELECT * FROM running_activities ORDER BY id") == saved
    assert query(dest, "SELECT file_sha256 FROM imports WHERE source = 'strava'") == [
        (hashlib.sha256(before).hexdigest(),)
    ] * 2
    assert source.read_bytes() == before


def test_overlap_updates_and_optional_elevation(tmp_path):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    write_csv(source, [RUN, row_with(id="124")])
    strava.import_file(source, dest)
    write_csv(source, [row_with(moving="500")[:-1]], HEADER[:-1])
    assert strava.import_file(source, dest).counts["updated"] == 1
    assert strava.import_file(source, dest).counts["unchanged"] == 1
    assert query(dest, "SELECT moving_time_s, elevation_gain_m, last_import_id FROM running_activities ORDER BY id") == [
        (500, 24.5, 2), (600, 24.5, 1),
    ]
    write_csv(source, [row_with(elevation="malformed")])
    assert strava.import_file(source, dest).counts["rejected"] == 1
    assert query(dest, "SELECT elevation_gain_m FROM running_activities WHERE source_record_id = '123'") == [(24.5,)]
    write_csv(source, [row_with(elevation="")])
    assert strava.import_file(source, dest).counts["updated"] == 1
    assert query(dest, "SELECT elevation_gain_m FROM running_activities WHERE source_record_id = '123'") == [(None,)]


@pytest.mark.parametrize("change", [
    {"id": "0123"}, {"date": "Feb 30, 2024, 4:00:00 PM"}, {"date": "Feb 29, 2024, 0:00:00 AM"},
    {"distance": "nan"}, {"moving": "701"}, {"elapsed": "-1"}, {"elevation": "inf"},
])
def test_invalid_rows_are_counted(tmp_path, change):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    write_csv(source, [row_with(**change), row_with(id="777", sport="Hike"), ()])
    assert strava.import_file(source, dest).counts == dict(
        inserted=0, updated=0, unchanged=0, rejected=2, unsupported=1
    )


@pytest.mark.parametrize("header,rows", [
    (HEADER + ("Distance",), []), (HEADER[1:], []),
    (HEADER, [RUN, row_with(sport="Walk")]),
])
def test_fatal_preflight_preserves_v1(tmp_path, header, rows):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    write_csv(source, rows, header)
    make_v1(dest)
    before = dest.read_bytes()
    with pytest.raises(db.FitnessError):
        strava.import_file(source, dest)
    assert dest.read_bytes() == before


def test_rollback_includes_migration(tmp_path, monkeypatch):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    write_csv(source, [RUN])
    make_v1(dest)

    def fail(*args):
        raise sqlite3.OperationalError("invented failure")

    monkeypatch.setattr(db, "finish_import", fail)
    with pytest.raises(sqlite3.OperationalError):
        strava.import_file(source, dest)
    assert query(dest, "PRAGMA user_version") == [(1,)]
    assert query(dest, "SELECT source FROM imports") == [("fitnotes",)]
    assert query(dest, "SELECT name FROM sqlite_schema WHERE name = 'running_activities'") == []
    assert strength_summary(dest)["repetitions"] == 7


def test_cli_and_weighted_pace_coverage(tmp_path, capsys):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    write_csv(source, [])
    args = ["--db", str(dest)]
    command = [*args, "import-strava", str(source)]
    assert main(command) == 0
    capsys.readouterr()
    assert running_summary(dest)["moving_pace_s_per_km"] is None
    write_csv(source, [
        row_with(distance="1000", moving="300"),
        row_with(id="124", distance="2000", moving="660"),
        row_with(id="125", distance="0", moving="300"),
        row_with(id="126", distance="3000", moving="", elevation=""),
        row_with(id="127", sport="Hike"),
    ])
    assert main(command) == 3
    assert json.loads(capsys.readouterr().out)["unsupported"] == 1
    assert main([*args, "running-summary"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "runs": 4, "recorded_running_days": 1, "moving_pace_s_per_km": 320,
        "runs_with_pace": 2, "distance_m": 6000, "runs_with_distance_m": 4,
        "moving_time_s": 1260, "runs_with_moving_time_s": 3,
        "elapsed_time_s": 2800, "runs_with_elapsed_time_s": 4,
        "elevation_gain_m": 73.5, "runs_with_elevation_gain_m": 3,
    }
    with pytest.raises(db.FitnessError, match="different files"):
        strava.import_file(source, source)


def test_weekly_summary_mixed_sources(tmp_path, capsys):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    make_v1(dest)
    with closing(sqlite3.connect(dest)) as connection, connection:
        connection.executemany(
            """INSERT INTO strength_sets
               (source, source_record_id, exercise_id, performed_on, repetitions, last_import_id)
               VALUES ('fitnotes', ?, 1, ?, ?, 1)""",
            [
                ("outside", "2023-12-29", 100),
                ("sunday", "2023-12-31", 5),
                ("same-day", "2024-01-01", 0),
                ("unknown", "2024-01-01", None),
                ("last-day", "2024-01-15", None),
                ("after", "2024-01-16", 100),
            ],
        )
    before = dest.read_bytes()
    legacy = weekly_summary(dest, "2024-01-01", "2024-01-01")
    assert legacy["weeks"][0]["strength"]["sets"] == 3
    assert legacy["weeks"][0]["running"]["runs"] == 0
    assert dest.read_bytes() == before
    write_csv(source, [
        row_with(date="Dec 31, 2023, 4:00:00 PM", distance="1000", moving="300"),
        row_with(id="124", date="Jan 1, 2024, 3:00:00 PM", distance="2000", moving="660"),
        row_with(id="125", date="Jan 2, 2024, 1:00:00 AM", distance="0", moving="300"),
        row_with(id="126", date="Jan 2, 2024, 1:00:00 AM", distance="500", moving="", elevation=""),
    ])
    assert strava.import_file(source, dest).counts["inserted"] == 4
    args = ["--db", str(dest), "weekly-summary", "--from", "2023-12-31", "--to", "2024-01-15"]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert main(args) == 0
    assert capsys.readouterr().out == output
    report = json.loads(output)
    assert report["reporting_timezone"] == "Asia/Singapore"
    assert (report["from"], report["to"]) == ("2023-12-31", "2024-01-15")
    assert report["observed_dates"] == {
        "strength": {"first": "2023-12-31", "last": "2024-01-15"},
        "running": {"first": "2024-01-01", "last": "2024-01-02"},
    }
    sunday, mixed, empty, last = report["weeks"]
    assert [week["week_start"] for week in report["weeks"]] == [
        "2023-12-25", "2024-01-01", "2024-01-08", "2024-01-15",
    ]
    assert sunday["strength"]["repetitions"] == 5
    assert mixed["recorded_training_days"] == 2
    assert mixed["strength"] == {
        "recorded_strength_days": 1, "sets": 3, "repetitions": 7, "sets_with_repetitions": 2,
    }
    assert mixed["running"] == running_summary(dest)
    assert mixed["running"]["moving_pace_s_per_km"] == 320
    assert mixed["running"]["runs_with_pace"] == 2
    assert mixed["running"]["runs_with_moving_time_s"] == 3
    assert mixed["running"]["runs_with_elevation_gain_m"] == 3
    assert empty["recorded_training_days"] == 0
    assert empty["running"]["distance_m"] is None
    assert empty["strength"]["repetitions"] is None
    assert last["strength"]["sets"] == 1
    assert last["strength"]["repetitions"] is None
    assert strength_summary(dest)["sets"] == 7


@pytest.mark.parametrize("start,end", [
    ("20240101", "2024-01-01"),
    ("2024-02-30", "2024-03-01"),
    ("2024-01-02", "2024-01-01"),
    ("2024-01-01", "2025-01-01"),
])
def test_weekly_invalid_range(tmp_path, capsys, start, end):
    dest = tmp_path / "missing.db"
    assert main(["--db", str(dest), "weekly-summary", "--from", start, "--to", end]) == 1
    assert capsys.readouterr().err.startswith("Error:")
    assert not dest.exists()


def test_weekly_empty_database_and_maximum_window(tmp_path):
    source, dest = tmp_path / "activities.csv", tmp_path / "fitness.db"
    write_csv(source, [])
    strava.import_file(source, dest)
    report = weekly_summary(dest, "2024-01-01", "2024-12-31")
    assert report["observed_dates"] == {"strength": None, "running": None}
    assert len(report["weeks"]) == 53
    assert all(week["recorded_training_days"] == 0 for week in report["weeks"])
