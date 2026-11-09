import json
from contextlib import closing
from datetime import date
from types import SimpleNamespace

import pytest

from test_llm import FakeClient, reply, response
from test_running_trends import make_database
from test_strava import make_v1
from unified_fitness import analytics, db, llm
from unified_fitness.cli import main


TODAY = date(2024, 3, 4)


def test_fastest_pace_respects_bands_and_excludes_unusable_inputs(tmp_path):
    path = tmp_path / "fitness.db"
    make_database(path, [
        ("2024-03-01", 4999, 100), ("2024-03-01", 5000, 1500), ("2024-03-01", 6000, 1800),
        ("2024-03-01", 7000, 2800), ("2024-03-01", 8000, None), ("2024-03-01", 9000, 0),
        ("2024-03-01", 10000, 2000), ("2024-03-01", 0, 100),
        ("2024-03-01", 5e-324, 100), ("2024-03-05", 5000, 100),
    ])
    before = path.read_bytes()
    result = analytics.running_records(path, "fastest_pace", distance_band="5_to_under_10_km", today=TODAY)
    assert result["runs"] == 9
    assert result["runs_in_band"] == 5
    assert result["eligible_runs"] == 3
    assert result["fastest_moving_pace_s_per_km"] == 300
    assert result["tied_runs"] == 2
    short = analytics.running_records(path, "fastest_pace", distance_band="under_5_km", today=TODAY)
    assert short["runs_in_band"] == 2
    assert short["eligible_runs"] == 1
    long = analytics.running_records(path, "fastest_pace", distance_band="10_km_or_more", today=TODAY)
    assert long["fastest_moving_pace_s_per_km"] == 200
    assert path.read_bytes() == before


def test_histograms_use_singapore_clock_and_include_modal_ties(tmp_path):
    path = tmp_path / "fitness.db"
    make_database(path, [("2024-03-01", 5000, 1500)] * 6 + [("2024-03-02", 5000, 1500)])
    with closing(db.connect(path, "rw")) as connection, connection:
        connection.executemany("UPDATE running_activities SET started_at_utc = ? WHERE id = ?", [
            ("2024-02-29T16:00:00+00:00", 1),  # 00:00 Friday
            ("2024-02-29T22:00:00Z", 2),       # 06:00 Friday
            ("2024-03-01T04:00:00+00:00", 3),  # 12:00 Friday
            ("2024-03-01T10:00:00+00:00", 4),  # 18:00 Friday
            ("2024-03-01T12:00:00", 5),        # unknown offset
            ("invalid", 6),
        ])
    clock = analytics.running_records(path, "time_of_day", today=TODAY)
    assert clock["runs"] == 7 and clock["eligible_runs"] == 4
    assert list(clock["buckets"].values()) == [1, 1, 1, 1]
    assert clock["most_common"] == list(analytics.TIME_BUCKETS)
    weekday = analytics.running_records(path, "weekday", "range", "2024-03-01", "2024-03-01", today=TODAY)
    assert weekday["eligible_runs"] == 6
    assert weekday["most_common"] == ["Friday"]
    assert weekday["buckets"]["Saturday"] == 0
    unavailable = analytics.running_records(path, "time_of_day", "range", "2024-03-02", "2024-03-02", today=TODAY)
    assert unavailable["status"] == "unavailable"
    assert unavailable["most_common"] == []


@pytest.mark.parametrize("fields", [
    {"metric": "fastest_pace"}, {"metric": "weekday", "distance_band": "under_5_km"},
    {"metric": "weekday", "mode": "comparison"}, {"metric": "time_of_day", "mode": "year", "year": 2025},
])
def test_invalid_record_options_fail_before_open(fields):
    with pytest.raises(db.FitnessError):
        analytics.running_records(None, today=TODAY, **fields)


def test_v1_reports_no_runs_without_migration(tmp_path):
    path = tmp_path / "legacy.db"
    make_v1(path)
    before = path.read_bytes()
    result = analytics.running_records(path, "weekday", today=TODAY)
    assert result["status"] == "empty"
    assert result["most_common"] == []
    assert path.read_bytes() == before


def record_call(metric, **overrides):
    fields = {"metric": metric, "mode": "all_time", "start": None, "end": None, "year": None,
              "distance_band": None, **overrides}
    return SimpleNamespace(type="function_call", name="get_running_records", call_id="record-1",
                           arguments=json.dumps(fields))


def test_chat_preserves_record_scope_through_band_clarification(tmp_path, monkeypatch, capsys):
    path = tmp_path / "private-path.db"
    make_database(path, [("2024-03-01", 5000, 1500)])
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    monkeypatch.setattr(analytics, "reporting_today", lambda: TODAY)
    assert main(["--db", str(path), "running-records", "fastest_pace", "--mode", "year", "--year", "2024",
                 "--distance-band", "5_to_under_10_km"]) == 0
    expected = json.loads(capsys.readouterr().out)
    call = record_call("fastest_pace", mode="year", year=2024, distance_band="5_to_under_10_km")
    client = FakeClient(reply("clarification", "Which distance band?"), response(call),
                        response(text="300 seconds per kilometer."))
    question = "What was my fastest running pace in 2024?"
    pending = llm.answer(client, "model", path, question)
    llm.answer(client, "model", path, "5 to under 10 km", pending=pending)
    first, second, final = client.requests
    assert first["tools"][-1]["strict"] is True
    assert [item["content"] for item in second["input"]] == [question, "5 to under 10 km"]
    output = final["input"][-1]
    assert output["call_id"] == "record-1"
    assert json.loads(output["output"]) == expected
    assert final["tool_choice"] == "none"
    assert all(private not in output["output"] for private in ("private-run-", "private-path", "2024-03-01"))


@pytest.mark.parametrize("call,question,clarification", [
    (record_call("fastest_pace", distance_band="under_5_km"), "What was my fastest run?", "Which distance band"),
    (record_call("fastest_pace"), "What was my fastest run?", "Which distance band"),
    (record_call("fastest_pace", distance_band="10_km_or_more"),
     "What was my fastest run over 110 km or more?", "Which distance band"),
    (record_call("fastest_pace", distance_band="5_to_under_10_km"),
     "What was my fastest run from 15 to 10 km?", "Which distance band"),
    (record_call("weekday"), "What is my most common running period?", "weekday or time of day"),
])
def test_chat_clarifies_missing_record_selector_before_read(monkeypatch, capsys, call, question, clarification):
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    monkeypatch.setattr(llm, "running_records", lambda *args, **kwargs: pytest.fail("Unexpected read"))
    client = FakeClient(response(call))
    assert llm.answer(client, "model", None, question) == question
    assert clarification in capsys.readouterr().out
    assert len(client.requests) == 1


def test_chat_weekday_defaults_to_all_time(tmp_path, monkeypatch):
    path = tmp_path / "fitness.db"
    make_database(path, [("2024-03-01", 5000, 1500)])
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    client = FakeClient(response(record_call("weekday")), response(text="Friday."))
    llm.answer(client, "model", path, "Which weekday do I run most often?")
    result = json.loads(client.requests[1]["input"][-1]["output"])
    assert result["most_common"] == ["Friday"]


def test_chat_can_clarify_year_then_distance_band(tmp_path, monkeypatch):
    path = tmp_path / "fitness.db"
    make_database(path, [("2024-03-01", 5000, 1500)])
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    call = record_call("fastest_pace", mode="year", year=2024, distance_band="5_to_under_10_km")
    client = FakeClient(reply("clarification", "Which year?"), response(call),
                        response(call), response(text="300 seconds per kilometer."))
    pending = llm.answer(client, "model", path, "What was my fastest recorded running pace?")
    pending = llm.answer(client, "model", path, "2024", pending=pending)
    assert "2024" in pending
    assert llm.answer(client, "model", path, "5 to under 10 km", pending=pending) is None
    assert len(client.requests) == 4
