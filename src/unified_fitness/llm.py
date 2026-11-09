"""Bounded OpenAI commentary on the local weekly report."""

import json
import os
import sqlite3
from pathlib import Path

from .analytics import report_dates, weekly_summary
from .db import FitnessError

MAX_QUESTION_CHARS = 2000
MAX_RESULT_BYTES = 32 * 1024
TOOL = {
    "type": "function",
    "name": "get_weekly_summary",
    "description": "Read recorded weekly strength and running totals for an inclusive range.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "Inclusive start date, YYYY-MM-DD."},
            "end": {"type": "string", "description": "Inclusive end date, YYYY-MM-DD."},
        },
        "required": ["start", "end"],
        "additionalProperties": False,
    },
}
INSTRUCTIONS = (
    "Answer only questions about recorded weekly strength and running totals. "
    "Use get_weekly_summary for evidence, only when both dates are unambiguous. "
    "Each question is independent. Do not guess dates or provide coaching. "
    "Use only the supplied evidence for numerical claims. Explain relevant missing metrics "
    "and coverage. Null means unavailable. Missing records do not establish inactivity."
)


def request(client, model, items, *, allow_tool):
    response = client.responses.create(
        model=model, input=items, instructions=INSTRUCTIONS, tools=[TOOL],
        tool_choice="auto" if allow_tool else "none", parallel_tool_calls=False,
        max_output_tokens=1024, store=False, include=["reasoning.encrypted_content"],
    )
    if response.status != "completed":
        raise FitnessError("OpenAI did not complete the response.")
    if any(item.type not in {"reasoning", "message", "function_call"} for item in response.output):
        raise FitnessError("OpenAI returned an unsupported response item.")
    return response


def unique_fields(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Duplicate fields")
    return fields


def tool_dates(arguments):
    try:
        if not isinstance(arguments, str) or len(arguments) > 256:
            raise ValueError
        fields = json.loads(arguments, object_pairs_hook=unique_fields)
        if not isinstance(fields, dict) or fields.keys() != {"start", "end"}:
            raise ValueError
        start, end = fields["start"], fields["end"]
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError
        report_dates(start, end)
    except (ValueError, FitnessError):
        raise FitnessError("Include two valid YYYY-MM-DD dates in order, spanning at most 366 days.") from None
    return start, end


def answer(client, model, path, question):
    if len(question) > MAX_QUESTION_CHARS:
        raise FitnessError(f"Keep questions to {MAX_QUESTION_CHARS} characters.")
    user_item = {"role": "user", "content": question}
    first = request(client, model, [user_item], allow_tool=True)
    calls = [item for item in first.output if item.type == "function_call"]
    if not calls:
        # A free-text response without evidence could contain invented training data.
        print("Ask about recorded weekly training and include the start and end dates in your question.")
        return
    if len(calls) != 1:
        raise FitnessError("OpenAI requested more than one tool call.")
    call = calls[0]
    if call.name != TOOL["name"] or not call.call_id:
        raise FitnessError("OpenAI requested an invalid tool call.")
    start, end = tool_dates(call.arguments)
    try:
        report = weekly_summary(path, start, end)
    except (FitnessError, sqlite3.Error, OSError, RuntimeError, ValueError):
        raise FitnessError("Cannot read the weekly report. Check the local database and schema.") from None
    try:
        evidence = json.dumps(report, allow_nan=False, separators=(",", ":"))
    except ValueError:
        raise FitnessError("The weekly report contains an unrepresentable value.") from None
    if len(evidence.encode("utf-8")) > MAX_RESULT_BYTES:
        raise FitnessError("The weekly report is too large for chat. Choose a shorter date range.")

    print("Deterministic evidence")
    print(json.dumps(report, indent=2, allow_nan=False))
    if all(bounds is None for bounds in report["observed_dates"].values()):
        print("No stored training records in this date range.")
        return
    print("Null metrics are unavailable. Coverage counts show how many records had usable inputs.")

    # Preserve the provider's item order while dropping draft prose.
    continuation = [
        user_item,
        *(item for item in first.output if item.type in {"reasoning", "function_call"}),
        {"type": "function_call_output", "call_id": call.call_id, "output": evidence},
    ]
    final = request(client, model, continuation, allow_tool=False)
    if any(item.type == "function_call" for item in final.output):
        raise FitnessError("OpenAI requested an extra tool call. The question has ended.")
    if not final.output_text.strip():
        raise FitnessError("OpenAI returned no commentary.")
    print("Model commentary")
    print(final.output_text)


def chat_settings():
    names = ("OPENAI_API_KEY", "OPENAI_MODEL")
    settings = {name: os.environ[name] for name in names if name in os.environ}
    if len(settings) == len(names):
        return tuple(settings[name].strip() for name in names)

    try:
        lines = Path(".env").read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeError):
        raise FitnessError("Cannot read .env. Check permissions and save it as UTF-8.") from None

    for line in lines:
        name, separator, value = line.partition("=")
        name = name.strip()
        if separator and name in names and name not in os.environ:
            value = value.strip()
            if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
                value = value[1:-1]
            settings[name] = value
    return tuple(settings.get(name, "").strip() for name in names)


def chat(path):
    key, model = chat_settings()
    if not key or not model:
        raise FitnessError("Set OPENAI_API_KEY and OPENAI_MODEL in the environment or .env to use chat.")
    try:
        import openai
    except ImportError:
        raise FitnessError('Install the chat dependency with pip install -e ".[ai]".') from None

    with openai.OpenAI(api_key=key, base_url="https://api.openai.com/v1",
                       timeout=30.0, max_retries=0,
                       http_client=openai.DefaultHttpxClient(follow_redirects=False)) as client:
        print("Chat sends questions and relevant weekly aggregates to OpenAI for remote processing.")
        print("Keep private details out of your questions. Type /quit to exit. Each question stands alone.")
        while True:
            try:
                question = input("You> ").strip()
                if question.lower() in {"/quit", "quit"}:
                    return 0
                if question:
                    answer(client, model, path, question)
            except (EOFError, KeyboardInterrupt):
                return 0
            except FitnessError as error:
                print(f"Error: {error}")
            except openai.APITimeoutError:
                print("Error: The OpenAI request timed out.")
            except openai.RateLimitError:
                print("Error: OpenAI rate or quota limit reached.")
            except openai.AuthenticationError:
                print("Error: OpenAI authentication failed. Check OPENAI_API_KEY.")
            except openai.OpenAIError:
                print("Error: The OpenAI request failed. Check connectivity and model access.")
