import json
from contextlib import closing
from datetime import date
from types import SimpleNamespace

import pytest

from test_llm import FakeClient, response
from test_strava import make_v1
from unified_fitness import analytics, db, llm
from unified_fitness.cli import main


TODAY = date(2024, 3, 4)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "private-path.db"
    make_v1(path)
    with closing(db.connect(path, "rw")) as connection, connection:
        connection.execute("INSERT INTO exercises VALUES (2, 'fitnotes', '2', 'Other Press', 0, 0)")
        connection.executemany(
            """INSERT INTO strength_sets
               (source, source_record_id, exercise_id, performed_on, repetitions, last_import_id)
               VALUES ('fitnotes', ?, ?, ?, ?, 1)""",
            [
                ("private-1", 1, "2024-02-01", 8),
                ("private-2", 1, "2024-02-29", 5),
                ("private-3", 1, "2024-02-29", None),
                ("private-4", 1, "2024-03-03", 0),
                ("private-5", 2, "2024-02-29", 99),
            ],
        )
    return path


def test_exercise_comparison_counts_days_and_suppresses_incomplete_reps(database):
    before = database.read_bytes()
    report = analytics.strength_activity(database, exercise="  INVENTED PRESS  ", today=TODAY)
    assert report["exercise"] == "INVENTED PRESS"
    baseline, current = report["periods"]
    assert (baseline["sets"], baseline["repetitions"], baseline["recorded_strength_days"]) == (1, 8, 1)
    assert (current["sets"], current["repetitions"], current["recorded_strength_days"]) == (3, 5, 2)
    assert current["sets_with_repetitions"] == 2
    assert report["comparison"]["changes"] == {
        "sets": {"delta": 2, "reason": None},
        "recorded_strength_days": {"delta": 1, "reason": None},
        "repetitions": {"delta": None, "reason": "incomplete_repetitions"},
    }
    assert "load_metrics_unavailable" in report["limitations"]
    assert current["load"]["max_load_kg"] is None
    assert current["load"]["volume_kg_reps"] is None
    assert current["load"]["estimated_1rm_kg"] is None
    assert database.read_bytes() == before


def test_overall_history_and_empty_period(database):
    year = analytics.strength_activity(database, "year", year=2024, today=TODAY)
    total, jan, feb, march = year["periods"]
    assert (total["sets"], total["repetitions"], total["recorded_strength_days"]) == (6, 119, 4)
    assert jan["sets"] == 1
    assert (feb["sets"], feb["recorded_strength_days"]) == (4, 2)
    assert march["partial"] is True and march["repetitions"] == 0
    empty = analytics.strength_activity(database, "range", "2024-02-02", "2024-02-03",
                                        exercise="Invented Press", today=TODAY)
    assert empty["status"] == "empty"
    assert empty["periods"][0]["repetitions"] is None


@pytest.mark.parametrize("exercise", ["Press", "Invented Press' OR 1=1 --"])
def test_non_exact_exercise_has_no_data(database, exercise):
    report = analytics.strength_activity(database, exercise=exercise, today=TODAY)
    assert report["status"] == "exercise_not_found"
    assert report["periods"] == []
    assert report["comparison"] is None


def test_casefold_collision_does_not_merge_exercises(database):
    with closing(db.connect(database, "rw")) as connection, connection:
        connection.execute("UPDATE exercises SET name = ? WHERE id = ?", (" invented PRESS ", 2))
    report = analytics.strength_activity(database, exercise="Invented Press", today=TODAY)
    assert report["status"] == "exercise_ambiguous"
    assert report["periods"] == []


def strength_call(exercise, **extra):
    fields = {"exercise": exercise, "mode": "all_time", "start": None, "end": None, "year": None, **extra}
    return SimpleNamespace(type="function_call", name="get_strength_progress", call_id="strength-1",
                           arguments=json.dumps(fields))


def test_chat_strength_evidence_matches_cli(database, monkeypatch, capsys):
    with closing(db.connect(database, "rw")) as connection, connection:
        connection.execute("UPDATE strength_sets SET load_kg = 60, load_kind = 'external' WHERE source_record_id = ?",
                           ("private-2",))
    monkeypatch.setattr(analytics, "reporting_today", lambda: TODAY)
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    exercise = "invented press"
    assert main(["--db", str(database), "strength-activity", "--mode", "all_time", "--exercise", exercise]) == 0
    offline = json.loads(capsys.readouterr().out)
    client = FakeClient(response(strength_call(exercise)), response(text="Recorded sets only."))
    llm.answer(client, "model", database, "How many sets of invented press have I recorded all time?")
    first, second = client.requests
    tool = next(tool for tool in first["tools"] if tool["name"] == "get_strength_progress")
    assert tool["name"] == "get_strength_progress"
    assert tool["strict"] is True
    assert "exercise" in tool["parameters"]["required"]
    assert second["tool_choice"] == "none"
    output = second["input"][-1]
    assert output["call_id"] == "strength-1"
    assert json.loads(output["output"]) == offline
    assert offline["periods"][0]["load"]["estimated_1rm_kg"] == 70
    assert all(private not in output["output"] for private in
               ("private-path", "private-1", "Invented Press", "Other Press"))


@pytest.mark.parametrize("call,diagnostic", [
    (strength_call("Other Press"), "full exercise name"),
    (strength_call(123), "full exercise name"),
    (strength_call("invented press", path="private.db"), "invalid report arguments"),
])
def test_chat_rejects_unrequested_exercise_before_read(monkeypatch, call, diagnostic):
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    monkeypatch.setattr(llm, "strength_activity", lambda *a, **kw: pytest.fail("Unexpected database read"))
    client = FakeClient(response(call))
    with pytest.raises(db.FitnessError, match=diagnostic):
        llm.answer(client, "model", None, "What is my all-time invented press activity?")
    assert len(client.requests) == 1


def test_unknown_exercise_ends_locally(database, monkeypatch, capsys):
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    client = FakeClient(response(strength_call("squat")))
    llm.answer(client, "model", database, "How many squat sets have I recorded all time?")
    assert len(client.requests) == 1
    assert "No exercise matched" in capsys.readouterr().out


def test_ambiguous_exercise_ends_locally(database, monkeypatch, capsys):
    with closing(db.connect(database, "rw")) as connection, connection:
        connection.execute("UPDATE exercises SET name = ? WHERE id = ?", ("Invented Press", 2))
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    client = FakeClient(response(strength_call("Invented Press")))
    llm.answer(client, "model", database, "How many Invented Press sets have I recorded all time?")
    assert len(client.requests) == 1
    assert "Multiple exercises share that name" in capsys.readouterr().out


def test_load_metrics_only_include_compatible_sets():
    rows = [("2024-02-29", reps, load, kind) for reps, load, kind in [
        (1, 100, "external"), (5, 90, "external"), (10, 70, "external"),
        (11, 60, "external"), (5, 200, "assisted"), (5, 300, None),
        (0, 400, "external"), (None, 500, "external"), (5, 0, "external"),
        (5, float("inf"), "external"), (5, None, "external"),
    ]]
    result = analytics.strength_load_metrics(rows)["load"]
    assert result == {"eligible_sets": 4, "estimate_sets": 2, "max_load_kg": 100,
                      "volume_kg_reps": 1910, "volume_is_subtotal": True, "estimated_1rm_kg": 105}


def test_load_comparison_requires_complete_coverage(database):
    with closing(db.connect(database, "rw")) as connection, connection:
        connection.execute("DELETE FROM strength_sets WHERE source_record_id IN ('private-3', 'private-4')")
        connection.execute("""UPDATE strength_sets
            SET load_kg = CASE WHEN source_record_id = 'private-1' THEN 60 ELSE 90 END,
                load_kind = 'external' WHERE exercise_id = 1""")
    report = analytics.strength_activity(database, exercise="Invented Press", today=TODAY)
    changes = report["comparison"]["load_changes"]
    assert changes["max_load_kg"] == {"delta": 30, "reason": None}
    assert changes["volume_kg_reps"] == {"delta": -30, "reason": None}
    assert changes["estimated_1rm_kg"]["delta"] == pytest.approx(29)
    with closing(db.connect(database, "rw")) as connection, connection:
        connection.execute("""INSERT INTO strength_sets
            (source, source_record_id, exercise_id, performed_on, repetitions, last_import_id)
            VALUES ('fitnotes', 'unmapped', 1, '2024-02-29', 5, 1)""")
    report = analytics.strength_activity(database, exercise="Invented Press", today=TODAY)
    assert report["periods"][1]["load"]["volume_kg_reps"] == 450
    assert report["comparison"]["load_changes"]["volume_kg_reps"] == {
        "delta": None, "reason": "incomplete_load_coverage",
    }


def test_load_overflow_is_unavailable():
    result = analytics.strength_load_metrics([("2024-02-29", 10, 1.7e308, "external")])["load"]
    assert result["max_load_kg"] == 1.7e308
    assert result["volume_kg_reps"] is None
    assert result["volume_is_subtotal"] is False
    assert result["estimated_1rm_kg"] is None
    json.dumps(result, allow_nan=False)
