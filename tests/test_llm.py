import json
import sys
from types import SimpleNamespace

import pytest

from test_strava import RUN, make_v1, row_with, write_csv
from unified_fitness import llm
from unified_fitness.cli import main
from unified_fitness.db import FitnessError
from unified_fitness.ingestion import strava


DATES = '{"start":"2024-01-01","end":"2024-03-01"}'


def tool_call(arguments=DATES, name="get_weekly_summary", call_id="call_123"):
    return SimpleNamespace(type="function_call", arguments=arguments, name=name,
                           call_id=call_id, id="fc_different")


def response(*items, text="", status="completed"):
    return SimpleNamespace(output=items, output_text=text, status=status)


class FakeClient:
    def __init__(self, *responses):
        self.responses = self
        self.pending = iter(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        result = next(self.pending)
        if isinstance(result, Exception):
            raise result
        return result

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


@pytest.fixture
def fitness_path(tmp_path):
    dest = tmp_path / "private-path.db"
    make_v1(dest)
    source = tmp_path / "private-source.csv"
    write_csv(source, [row_with(RUN, id="987654321", elevation="")])
    assert strava.import_file(source, dest).counts["inserted"] == 1
    return dest


def test_evidence_matches_offline_cli(fitness_path, capsys):
    before = fitness_path.read_bytes()
    assert main(["--db", str(fitness_path), "weekly-summary",
                 "--from", "2024-01-01", "--to", "2024-03-01"]) == 0
    offline = json.loads(capsys.readouterr().out)
    question = "What was recorded from 2024-01-01 to 2024-03-01?"
    call = tool_call()
    reasoning = SimpleNamespace(type="reasoning", encrypted_content="opaque")
    draft = SimpleNamespace(type="message", content="discard this draft")
    later_reasoning = SimpleNamespace(type="reasoning", encrypted_content="second opaque item")
    client = FakeClient(response(reasoning, call, draft, later_reasoning),
                        response(text="Invented commentary"))
    llm.answer(client, "configured-model", fitness_path, question)
    first, second = client.requests
    user = {"role": "user", "content": question}
    assert first["input"] == [user]
    assert first["tool_choice"] == "auto"
    assert second["input"][:4] == [user, reasoning, call, later_reasoning]
    output = second["input"][4]
    assert output["type"] == "function_call_output"
    assert output["call_id"] == call.call_id
    assert json.loads(output["output"]) == offline
    assert offline["weeks"][-1]["running"]["elevation_gain_m"] is None
    assert second["tool_choice"] == "none"
    for request in client.requests:
        assert request["store"] is False
        assert request["parallel_tool_calls"] is False
        assert request["model"] == "configured-model"
        assert request["max_output_tokens"] == 1024
        tool, = request["tools"]
        assert tool["name"] == "get_weekly_summary"
        assert tool["strict"] is True
        assert tool["parameters"]["required"] == ["start", "end"]
        assert tool["parameters"]["additionalProperties"] is False
        assert {"previous_response_id", "conversation"}.isdisjoint(request)
        for private in (str(fitness_path), "987654321", "Invented Press", "discard this draft"):
            assert private not in repr(request)
    displayed = capsys.readouterr().out
    assert displayed.index("Deterministic evidence") < displayed.index("Model commentary")
    assert "Null metrics are unavailable" in displayed
    assert fitness_path.read_bytes() == before


@pytest.mark.parametrize("arguments", [
    "{", "[]", '{"start":1,"end":null}', '{"start":"2024-01-01"}',
    DATES[:-1] + ',"path":"secret"}', DATES[:-1] + ',"start":"2024-01-02"}',
    DATES.replace("2024-01-01", "20240101"), DATES.replace("2024-03-01", "2023-12-31"),
    DATES.replace("2024-03-01", "2025-01-01"), " " * 257,
])
def test_invalid_tool_arguments_stop_before_read(arguments, monkeypatch):
    monkeypatch.setattr(llm, "weekly_summary", lambda *_: pytest.fail("Unexpected database read"))
    client = FakeClient(response(tool_call(arguments)))
    with pytest.raises(FitnessError, match="two valid YYYY-MM-DD dates"):
        llm.answer(client, "model", None, "question")
    assert len(client.requests) == 1


@pytest.mark.parametrize("result,message", [
    (response(tool_call(name="unknown")), "invalid tool"),
    (response(tool_call(call_id="")), "invalid tool"),
    (response(tool_call(), tool_call()), "more than one"),
    (response(status="incomplete"), "did not complete"),
    (response(SimpleNamespace(type="web_search_call")), "unsupported response"),
])
def test_invalid_provider_responses_stop_before_read(result, message, monkeypatch):
    monkeypatch.setattr(llm, "weekly_summary", lambda *_: pytest.fail("Unexpected database read"))
    client = FakeClient(result)
    with pytest.raises(FitnessError, match=message):
        llm.answer(client, "model", None, "question")
    assert len(client.requests) == 1


@pytest.mark.parametrize("result,message", [
    (response(tool_call()), "extra tool call"),
    (response(status="incomplete"), "did not complete"),
    (response(), "no commentary"),
])
def test_second_response_cannot_trigger_more_requests(fitness_path, capsys, result, message):
    client = FakeClient(response(tool_call()), result)
    with pytest.raises(FitnessError, match=message):
        llm.answer(client, "model", fitness_path, "question")
    assert len(client.requests) == 2
    displayed = capsys.readouterr().out
    assert "Deterministic evidence" in displayed
    assert "Model commentary" not in displayed


def test_no_tool_and_empty_range(fitness_path, capsys):
    client = FakeClient(response(text="You ran 99 times."), response(
        tool_call(DATES.replace("2024", "2025"))))
    llm.answer(client, "model", fitness_path, "first question")
    assert "include the start and end dates" in capsys.readouterr().out
    llm.answer(client, "model", fitness_path, "second question")
    assert "No stored training records" in capsys.readouterr().out
    assert [request["input"] for request in client.requests] == [
        [{"role": "user", "content": "first question"}],
        [{"role": "user", "content": "second question"}],
    ]


def test_result_boundary(fitness_path, monkeypatch):
    client = FakeClient(response(tool_call()), response(tool_call()))
    with pytest.raises(FitnessError, match="Keep questions"):
        llm.answer(client, "model", fitness_path, "x" * (llm.MAX_QUESTION_CHARS + 1))
    assert client.requests == []
    monkeypatch.setattr(llm, "MAX_RESULT_BYTES", 1)
    with pytest.raises(FitnessError, match="too large"):
        llm.answer(client, "model", fitness_path, "question")
    monkeypatch.setattr(llm, "weekly_summary", lambda *_: {"metric": float("inf")})
    with pytest.raises(FitnessError, match="unrepresentable"):
        llm.answer(client, "model", fitness_path, "question")
    assert all(len(request["input"]) == 1 for request in client.requests)


def test_chat_errors_and_disclosure(monkeypatch, capsys, tmp_path):
    class APIError(Exception):
        pass

    class Timeout(APIError):
        pass

    class RateLimit(APIError):
        pass

    class Authentication(APIError):
        pass

    client = FakeClient(*(kind("private error body") for kind in
                          (Timeout, RateLimit, Authentication, APIError)), response(tool_call()))

    transport = object()

    def create_transport(*, follow_redirects):
        assert follow_redirects is False
        return transport

    def create_client(**kwargs):
        assert kwargs == dict(api_key="invented-key", base_url="https://api.openai.com/v1",
                              timeout=30.0, max_retries=0, http_client=transport)
        return client

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        OpenAI=create_client, DefaultHttpxClient=create_transport,
        OpenAIError=APIError, APITimeoutError=Timeout,
        RateLimitError=RateLimit, AuthenticationError=Authentication,
    ))
    monkeypatch.setenv("OPENAI_API_KEY", "invented-key")
    monkeypatch.setenv("OPENAI_MODEL", "invented-model")
    questions = iter(["first", "second", "third", "fourth", "fifth"])
    observed = []

    def read_question(_):
        observed.append(capsys.readouterr().out)
        return next(questions)

    def input_or_eof(prompt):
        try:
            return read_question(prompt)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", input_or_eof)
    assert main(["--db", str(tmp_path / "private-path.db"), "chat"]) == 0
    assert "remote processing" in observed[0]
    assert [request["input"][0]["content"] for request in client.requests] == [
        "first", "second", "third", "fourth", "fifth",
    ]
    for message, output in zip(("timed out", "quota limit", "authentication failed",
                                "request failed", "Cannot read"), observed[1:], strict=True):
        assert message in output
        assert all(private not in output for private in ("private error body", "invented-key", "private-path.db"))


def test_offline_without_sdk_or_credentials(fitness_path, monkeypatch, capsys):
    monkeypatch.chdir(fitness_path.parent)
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    args = ["--db", str(fitness_path)]
    assert main([*args, "summary"]) == 0
    assert main([*args, "running-summary"]) == 0
    assert main([*args, "weekly-summary", "--from", "2024-01-01", "--to", "2024-03-01"]) == 0
    assert main([*args, "chat"]) == 1
    assert "Set OPENAI_API_KEY and OPENAI_MODEL" in capsys.readouterr().err
    monkeypatch.setenv("OPENAI_API_KEY", "invented-key")
    monkeypatch.setenv("OPENAI_MODEL", "invented-model")
    assert main([*args, "chat"]) == 1
    assert 'pip install -e ".[ai]"' in capsys.readouterr().err


@pytest.mark.parametrize("existing_model", [None, "process-model", ""])
def test_chat_loads_dotenv_with_process_precedence(tmp_path, monkeypatch, capsys, existing_model):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    if existing_model is not None:
        monkeypatch.setenv("OPENAI_MODEL", existing_model)
    (tmp_path / ".env").write_text(
        '# Example\nOPENAI_API_KEY = "invented-key"\nOPENAI_MODEL=file-model\n'
        'UNIFIED_FITNESS_DB=ignored.db\n', encoding="utf-8-sig",
    )
    client = FakeClient(response())

    def create_client(**kwargs):
        assert kwargs["api_key"] == "invented-key"
        return client

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(
        OpenAI=create_client, DefaultHttpxClient=lambda **_: None,
    ))
    questions = iter(["question", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(questions))
    if existing_model == "":
        assert main(["chat"]) == 1
        assert "Set OPENAI_API_KEY and OPENAI_MODEL" in capsys.readouterr().err
        assert client.requests == []
    else:
        assert main(["chat"]) == 0
        request, = client.requests
        assert request["model"] == (existing_model or "file-model")
