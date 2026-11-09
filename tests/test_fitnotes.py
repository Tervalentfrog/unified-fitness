import hashlib
import json
import os
import sqlite3
from contextlib import closing

import pytest

from unified_fitness import db
from unified_fitness.analytics import strength_summary
from unified_fitness.cli import main
from unified_fitness.ingestion.fitnotes import import_file

SET = (1, 10, "2024-02-29", 7, 123, 0, 0, 9, 0, 1)
EXERCISES = [(10, "Invented Press", 0, 4), (11, "Unused", 1, 0)]


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "source.fitnotes", tmp_path / "destination.sqlite3"


def backup(path, rows=(), *, version=22):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(f"""
            PRAGMA user_version = {version};
            CREATE TABLE exercise (_id, name, exercise_type_id, weight_unit_id);
            CREATE TABLE training_log (_id, exercise_id, date, reps, metric_weight,
                distance, duration_seconds, unit, is_complete, is_pending_update);
            CREATE TABLE settings (metric, mark_sets_complete);
            INSERT INTO settings VALUES (1, 0);
        """)
        connection.executemany("INSERT INTO exercise VALUES (?, ?, ?, ?)", EXERCISES)
        connection.executemany("INSERT INTO training_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def execute(path, sql):
    with closing(sqlite3.connect(path)) as connection, connection:
        return connection.execute(sql).fetchall()


def run(paths):
    return import_file(*paths, assume_performed=True)


def test_repeat_raw_values_and_summary(paths):
    source, dest = paths
    backup(source, [SET, (2, *SET[1:]), (3, 10, "2024-03-01", *SET[3:])])
    original = hashlib.sha256(source.read_bytes()).digest()
    first = run(paths)
    assert first.counts["inserted"] == 3
    assert first.warnings
    assert execute(dest, "SELECT source_exercise_id, source_type_id, source_weight_unit_id FROM exercises") == [
        ("10", 0, 4)
    ]
    saved = execute(dest, "SELECT * FROM strength_sets ORDER BY id")
    assert execute(dest, """SELECT source_record_id, performed_on, repetitions, source_load, source_unit_code,
                                    source_is_complete, source_is_pending_update,
                                    load_kg, source_load_unit, load_kind, set_order FROM strength_sets
                                    WHERE source_record_id = '1'""") == [
        ("1", "2024-02-29", 7, 123, 9, 0, 1, None, None, None, None)
    ]
    assert run(paths).counts == dict(inserted=0, updated=0, unchanged=3, rejected=0, unsupported=0)
    assert execute(dest, "SELECT * FROM strength_sets ORDER BY id") == saved
    options = [json.loads(row[0]) for row in execute(dest, "SELECT options_json FROM imports")]
    assert len(options) == 2
    assert options[0]["assume_performed"] is True
    assert options[0]["source_schema_version"] == 22
    assert options[0]["settings"] == {"metric": 1, "mark_sets_complete": 0}
    assert strength_summary(dest) == {
        "sets": 3, "repetitions": 21, "recorded_training_days": 2,
        "exercises": [{"exercise": "Invented Press", "sets": 3, "repetitions": 21}],
    }
    assert hashlib.sha256(source.read_bytes()).digest() == original
    assert execute(dest, "PRAGMA foreign_key_check") == []


def test_synthetic_same_id_update_and_absence(paths):
    source, dest = paths
    backup(source, [SET, (2, *SET[1:])])
    run(paths)
    execute(source, "DELETE FROM training_log WHERE _id = 2")
    execute(source, "UPDATE training_log SET reps = 8, metric_weight = 123.5")
    execute(source, "UPDATE exercise SET name = 'Invented Rename' WHERE _id = 10")
    assert run(paths).counts["updated"] == 1
    assert run(paths).counts["unchanged"] == 1
    assert execute(dest, "SELECT source_record_id, repetitions, source_load, last_import_id FROM strength_sets ORDER BY id") == [
        ("1", 8, 123.5, 2), ("2", 7, 123, 1)
    ]
    execute(source, "UPDATE training_log SET unit = NULL")
    assert run(paths).counts["rejected"] == 1
    assert strength_summary(dest)["repetitions"] == 15
    assert strength_summary(dest)["exercises"][0]["exercise"] == "Invented Rename"


@pytest.mark.parametrize(("index", "value", "outcome"), [
    (0, "01", "rejected"), (1, 999, "rejected"), (2, "2023-02-29", "rejected"),
    (2, "2024-02-29T00:00", "rejected"), (3, 3.5, "rejected"), (3, -1, "rejected"),
    (4, float("inf"), "rejected"), (4, -1, "rejected"), (7, "bad", "rejected"),
    (8, 2, "rejected"), (9, None, "rejected"), (1, 11, "unsupported"),
    (5, 1, "unsupported"), (6, 1, "unsupported"),
])
def test_each_invalid_or_unsupported_row_counted_once(paths, index, value, outcome):
    row = list(SET)
    row[index] = value
    backup(paths[0], [row])
    result = run(paths)
    assert result.counts[outcome] == sum(result.counts.values()) == 1
    assert sum(result.diagnostics.values()) == 1
    assert execute(paths[1], "SELECT * FROM exercises") == []


@pytest.mark.parametrize("sql", [
    "PRAGMA user_version = 21",
    "ALTER TABLE training_log DROP COLUMN unit",
    "INSERT INTO training_log SELECT * FROM training_log",
])
def test_bad_source_preflight_preserves_existing_destination(paths, sql):
    source, dest = paths
    backup(source, [SET])
    run(paths)
    before = dest.read_bytes()
    execute(source, sql)
    with pytest.raises(db.FitnessError):
        run(paths)
    assert dest.read_bytes() == before


def test_invalid_exercise_type(paths):
    backup(paths[0], [SET])
    execute(paths[0], "UPDATE exercise SET exercise_type_id = 'bad'")
    assert run(paths).counts["rejected"] == 1


def test_incompatible_destination(paths):
    source, dest = paths
    backup(source, [SET])
    execute(dest, "CREATE TABLE existing (value)")
    before = dest.read_bytes()
    with pytest.raises(db.FitnessError, match="Incompatible destination"):
        run(paths)
    assert dest.read_bytes() == before


def test_rollback_after_domain_write(paths, monkeypatch):
    source, dest = paths
    backup(source, [SET])
    run(paths)
    execute(source, "UPDATE training_log SET reps = 10")
    original = db.finish_import

    def fail(*args):
        original(*args)
        raise sqlite3.OperationalError("synthetic write failure")

    monkeypatch.setattr(db, "finish_import", fail)
    with pytest.raises(db.FitnessError, match="Could not import"):
        run(paths)
    assert execute(dest, "SELECT repetitions, last_import_id FROM strength_sets") == [(7, 1)]
    assert execute(dest, "SELECT count(*) FROM imports") == [(1,)]


def test_empty_and_cli_statuses(paths, capsys):
    source, dest = paths
    backup(source)
    args = ["--db", str(dest)]
    command = [*args, "import-fitnotes", str(source)]
    assert main(command) == 1
    assert "assume-performed" in capsys.readouterr().err
    assert not dest.exists()
    assert main([*args, "summary"]) == 1
    capsys.readouterr()
    assert main([*command, "--assume-performed"]) == 0
    assert sum(json.loads(capsys.readouterr().out).values()) == 0
    assert main([*args, "summary"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "sets": 0, "repetitions": 0, "recorded_training_days": 0, "exercises": [],
    }
    execute(source, "INSERT INTO training_log (_id, exercise_id) VALUES (1, 999)")
    assert main([*command, "--assume-performed"]) == 3
    assert json.loads(capsys.readouterr().out)["rejected"] == 1
    with pytest.raises(SystemExit) as error:
        main([*args, "invalid-command"])
    assert error.value.code == 2


def test_source_destination_aliases(paths):
    source, dest = paths
    backup(source, [SET])
    before = source.read_bytes()
    with pytest.raises(db.FitnessError, match="different files"):
        run((source, source))
    os.link(source, dest)
    with pytest.raises(db.FitnessError, match="different files"):
        run(paths)
    assert source.read_bytes() == before


def test_source_sidecar_is_rejected(paths):
    source, dest = paths
    backup(source, [SET])
    source.with_suffix(".fitnotes-wal").touch()
    with pytest.raises(db.FitnessError, match="standalone"):
        run(paths)
    assert not dest.exists()


def test_destination_sidecar_cannot_be_source(paths):
    _, dest = paths
    source = dest.with_suffix(".sqlite3-journal")
    backup(source, [SET])
    before = source.read_bytes()
    with pytest.raises(db.FitnessError, match="different files"):
        run((source, dest))
    assert source.read_bytes() == before
    assert not dest.exists()
