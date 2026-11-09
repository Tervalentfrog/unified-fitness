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


def make_database(path, rows):
    with closing(db.connect(path, "rwc")) as connection, connection:
        db.check_schema(connection, initialize=True)
        connection.execute("""INSERT INTO imports
            (source, file_sha256, imported_at_utc, adapter_version, options_json, inserted)
            VALUES ('strava', 'invented', '2024-03-01T00:00:00+00:00', 1, '{}', 1)""")
        connection.executemany("""INSERT INTO running_activities
            (source, source_record_id, activity_date, distance_m, moving_time_s, elapsed_time_s, last_import_id)
            VALUES ('strava', ?, ?, ?, ?, 10000, 1)""",
            [(f"private-run-{index}", *row) for index, row in enumerate(rows)])


def test_weighted_pace_and_mixed_band_comparison(tmp_path):
    path = tmp_path / "fitness.db"
    baseline = [(1000, 300), (2000, 800), (3000, 900), (5000, 1500), (6000, 1800), (7000, 2100)]
    current = [(1000, 240), (2000, 600), (3000, 900), (5000, 1800), (6000, 2160), (7000, 2520),
               (10000, 3500), (None, 100), (0, 100), (4000, None)]
    make_database(path, [("2024-02-01", *run) for run in baseline]
                  + [("2024-02-29", *run) for run in current])
    before = path.read_bytes()
    report = analytics.running_trends(path, today=TODAY)
    first, last = report["periods"]
    assert (first["start"], first["end"]) == ("2024-01-08", "2024-02-04")
    assert (last["start"], last["end"]) == ("2024-02-05", "2024-03-03")
    assert (last["runs"], last["recorded_running_days"]) == (10, 1)
    assert last["runs_with_pace"] == 7
    with closing(db.connect(path, "ro")) as connection:
        distance, seconds = connection.execute("""SELECT SUM(distance_m), SUM(moving_time_s)
            FROM running_activities WHERE activity_date = ? AND distance_m > 0 AND moving_time_s > 0""",
            ("2024-02-29",)).fetchone()
    assert last["pace_distance_m"] == distance
    assert last["moving_pace_s_per_km"] == pytest.approx(seconds / (distance / 1000))
    comparison = report["comparison"]
    assert comparison["pace_direction"] == "mixed"
    short, medium, long = comparison["pace_bands"]
    assert short["delta_s_per_km"] == pytest.approx((1740 - 2000) / 6)
    assert medium["delta_s_per_km"] == 60
    assert long["current"]["runs_with_pace"] == 1
    assert long["reason"] == "insufficient_comparable_runs"
    assert comparison["changes"]["runs"]["delta"] == 4
    assert comparison["changes"]["distance_m"] == {"delta": None, "reason": "incomplete_distance"}
    assert path.read_bytes() == before


def test_yearly_cap_empty_years_and_all_time(tmp_path):
    path = tmp_path / "fitness.db"
    make_database(path, [("2000-01-01", 500, 100), ("2014-01-01", 1000, 250),
                         ("2024-02-29", 2000, 500), ("2024-03-05", 9000, 900)])
    yearly = analytics.running_trends(path, "yearly", today=TODAY)
    assert [p["label"] for p in yearly["periods"]] == [str(y) for y in range(2013, 2025)]
    assert yearly["periods"][0]["runs"] == 0
    assert yearly["periods"][0]["distance_m"] is None
    assert yearly["periods"][-1]["partial"] is True
    assert "earlier_years_omitted" in yearly["limitations"]
    assert yearly["comparison"] is None
    total, = analytics.running_trends(path, "all_time", today=TODAY)["periods"]
    assert (total["start"], total["end"], total["runs"], total["distance_m"]) == (
        "2000-01-01", "2024-03-04", 3, 3500,
    )
    year = analytics.running_trends(path, "year", year=2024, today=TODAY)
    assert [(p["label"], p["end"], p["partial"]) for p in year["periods"]] == [
        ("total", "2024-03-04", True), ("2024-01", "2024-01-31", False),
        ("2024-02", "2024-02-29", False), ("2024-03", "2024-03-04", True),
    ]


def test_weekly_range_and_empty_comparison(tmp_path):
    path = tmp_path / "legacy.db"
    make_v1(path)
    before = path.read_bytes()
    report = analytics.running_trends(path, "range", "2024-02-28", "2024-03-04", today=TODAY)
    assert report["status"] == "empty"
    assert [(p["start"], p["end"], p["partial"]) for p in report["periods"][1:]] == [
        ("2024-02-28", "2024-03-03", True), ("2024-03-04", "2024-03-04", True),
    ]
    comparison = analytics.running_trends(path, "comparison", "2024-02-29", "2024-03-04", today=TODAY)
    assert comparison["periods"][0]["start"] == "2024-02-24"
    assert comparison["comparison"]["changes"]["runs"] == {"delta": None, "reason": "empty_period"}
    assert path.read_bytes() == before


@pytest.mark.parametrize("kwargs", [
    {"mode": "range"},
    {"mode": "all_time", "start": "2024-01-01", "end": "2024-01-02"},
    {"mode": "year", "year": 2025},
    {"mode": "year", "year": True},
    {"start": "0001-01-01", "end": "0001-01-01"},
    {"start": "2022-01-01", "end": "2024-01-01"},
    {"mode": "range", "start": "2024-03-04", "end": "2024-03-05"},
])
def test_invalid_window_is_rejected_before_database_open(kwargs):
    with pytest.raises(db.FitnessError):
        analytics.running_trends(None, today=TODAY, **kwargs)


def running_call(mode, **fields):
    return SimpleNamespace(type="function_call", name="get_running_trends", call_id="running-1",
                           arguments=json.dumps({"mode": mode, "start": None, "end": None,
                                                 "year": None, **fields}))


@pytest.mark.parametrize("mode,question", [
    ("all_time", "What is my all-time running distance?"),
    ("yearly", "Show my running history by year."),
    ("comparison", "Is my running pace improving?"),
    ("range", "Show weekly running distance from 2024-02-01 through 2024-03-04."),
    ("year", "Show my monthly running distance in 2024."),
])
def test_chat_running_evidence_matches_offline(tmp_path, monkeypatch, capsys, mode, question):
    path = tmp_path / "private-path.db"
    make_database(path, [("2024-02-29", 2000, 500)])
    monkeypatch.setattr(analytics, "reporting_today", lambda: TODAY)
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    flags, fields = [], {}
    if mode == "range":
        fields = {"start": "2024-02-01", "end": "2024-03-04"}
        flags = ["--from", fields["start"], "--to", fields["end"]]
    elif mode == "year":
        fields, flags = {"year": 2024}, ["--year", "2024"]
    assert main(["--db", str(path), "running-trends", "--mode", mode, *flags]) == 0
    expected = json.loads(capsys.readouterr().out)
    call = running_call(mode, **fields)
    client = FakeClient(response(call), response(text="Grounded commentary."))
    llm.answer(client, "model", path, question)
    first, second = client.requests
    assert [tool["name"] for tool in first["tools"]] == ["get_weekly_summary", "get_running_trends"]
    assert first["parallel_tool_calls"] is False
    assert second["tool_choice"] == "none"
    output = second["input"][-1]
    assert output["call_id"] == call.call_id
    assert json.loads(output["output"]) == expected
    assert str(path) not in output["output"] and "private-run-" not in output["output"]
    assert "Grounded commentary." in capsys.readouterr().out


@pytest.mark.parametrize("mode,question", [
    ("all_time", "How has my pace changed?"),
    ("comparison", "What was my average pace last year?"),
])
def test_chat_rejects_unrequested_history(monkeypatch, mode, question):
    monkeypatch.setattr(llm, "running_trends", lambda *_args, **_kwargs: pytest.fail("Unexpected read"))
    client = FakeClient(response(running_call(mode)))
    with pytest.raises(db.FitnessError, match="scope did not match"):
        llm.answer(client, "model", None, question)
    assert len(client.requests) == 1


def test_chat_rejects_extra_tools_before_read(monkeypatch):
    monkeypatch.setattr(llm, "running_trends", lambda *_args, **_kwargs: pytest.fail("Unexpected read"))
    monkeypatch.setattr(llm, "weekly_summary", lambda *_: pytest.fail("Unexpected read"))
    client = FakeClient(response(running_call("comparison"), running_call("all_time")))
    with pytest.raises(db.FitnessError, match="more than one"):
        llm.answer(client, "model", None, "How has my pace changed?")
    assert len(client.requests) == 1


def test_running_trends_report_is_finite(tmp_path):
    path = tmp_path / "fitness.db"
    make_database(path, [("2024-02-29", 1e308, 500), ("2024-02-29", 1e308, 500),
                         ("2024-02-29", 5e-324, 500)])
    report = analytics.running_trends(path, "all_time", today=TODAY)
    total, = report["periods"]
    assert total["distance_m"] is None
    assert total["pace_distance_m"] is None
    assert total["moving_pace_s_per_km"] is None
    assert total["runs_with_pace"] == 3
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("scope,mode,fields", [
    ("In 2024.", "year", {"year": 2024}),
    ("By year", "yearly", {}),
    ("All time", "all_time", {}),
])
def test_running_clarification_keeps_pending_question(tmp_path, monkeypatch, scope, mode, fields):
    path = tmp_path / "fitness.db"
    make_database(path, [("2024-02-29", 2000, 500)])
    monkeypatch.setattr(llm, "reporting_today", lambda: TODAY)
    pending = "Show my running distance."
    client = FakeClient(response(running_call(mode, **fields)), response(text="Recorded distance."))
    assert llm.answer(client, "model", path, scope, pending=pending) is None
    assert [item["content"] for item in client.requests[0]["input"]] == [pending, scope]
    assert len(client.requests) == 2


def test_pace_underflow_does_not_report_zero():
    metrics = analytics.pace_metrics([("2024-02-29", 1e308, 5e-324, None, None)])
    assert metrics["moving_pace_s_per_km"] is None
    assert metrics["runs_with_pace"] == 1
