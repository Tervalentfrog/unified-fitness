"""Bounded OpenAI commentary on the local weekly report."""

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .analytics import (
    RUNNING_MODES, monday, report_dates, reporting_today, running_trends, running_window, weekly_summary,
)
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
RUNNING_TOOL = {
    "type": "function",
    "name": "get_running_trends",
    "description": (
        "Read recorded running distance, frequency, and moving pace. Use comparison for changes "
        "or improvement, range for weekly running within dates, year for one year's monthly "
        "breakdown, yearly for calendar-year history, and all_time for lifetime totals. "
        "Use get_weekly_summary for combined running and strength. No fastest-run or start-time data."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": list(RUNNING_MODES)},
            "start": {"type": ["string", "null"], "description": "Inclusive ISO start for range or comparison."},
            "end": {"type": ["string", "null"], "description": "Inclusive ISO end for range or comparison."},
            "year": {"type": ["integer", "null"], "description": "Calendar year for year mode only."},
        },
        "required": ["mode", "start", "end", "year"],
        "additionalProperties": False,
    },
}
INSTRUCTIONS = (
    "Answer general questions directly. Never make claims about the user's recorded training "
    "without tool evidence. If the question needs a date range and it is unclear, "
    "ask one focused clarification; do not guess dates. Use locally resolved dates when supplied, "
    "otherwise require both dates in YYYY-MM-DD form for explicit ranges. Running trends can use "
    "an explicitly requested year, yearly or all-time scope, or the default comparison for change questions. "
    "In running comparisons use pace_direction and eligible distance bands; overall pace is descriptive. "
    "Never infer inactivity or improvement from empty periods or infer causal effects. "
    "If the available tool cannot answer the question, explain the specific limitation. "
    "Use only the supplied evidence for claims about recorded training. Explain relevant missing "
    "metrics and coverage. Null means unavailable. Missing records do not establish inactivity."
)
REPLY_FORMAT = {
    "type": "json_schema",
    "name": "chat_reply",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["answer", "clarification", "unavailable"]},
            "message": {"type": "string"},
        },
        "required": ["kind", "message"],
        "additionalProperties": False,
    },
}
RELATIVE_PERIOD = r"\b(?:today|yesterday|(?:this|last) (?:week|month))\b"
ISO_DATE = r"\b\d{4}-\d{2}-\d{2}\b"
YEARLY_SCOPE = r"\b(?:yearly|by year|per year|year[- ]by[- ]year|annual(?:ly)?|each year|over the years)\b"
ALL_TIME_SCOPE = r"\b(?:all[- ]time|lifetime|ever|entire history|across all years)\b"
DATE_REPLY = (
    rf"(?:{RELATIVE_PERIOD}|{ISO_DATE}(?:\s+(?:to|through)\s+{ISO_DATE})?"
    rf"|(?:in\s+)?\d{{4}}|{YEARLY_SCOPE}|{ALL_TIME_SCOPE})[.!]?"
)


def request(client, model, items, *, allow_tool, resolved=None):
    instructions = INSTRUCTIONS
    options = {}
    if allow_tool:
        options["text"] = {"format": REPLY_FORMAT}
        instructions += (
            " If no tool is called, classify the reply as answer for general information, "
            "clarification for a missing date range, or unavailable for unsupported analysis."
        )
    if resolved:
        instructions += f" The locally resolved reporting range is {resolved[0]} through {resolved[1]}."
    response = client.responses.create(
        model=model, input=items, instructions=instructions, tools=[TOOL, RUNNING_TOOL],
        tool_choice="auto" if allow_tool else "none", parallel_tool_calls=False,
        max_output_tokens=1024, store=False, include=["reasoning.encrypted_content"], **options,
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


def running_arguments(arguments, today):
    try:
        if not isinstance(arguments, str) or len(arguments) > 256:
            raise ValueError
        fields = json.loads(arguments, object_pairs_hook=unique_fields)
        if not isinstance(fields, dict) or fields.keys() != {"mode", "start", "end", "year"}:
            raise ValueError
    except ValueError:
        raise FitnessError("OpenAI requested invalid running trend arguments.") from None
    running_window(**fields, today=today)
    return fields


def running_scope_matches(fields, question):
    mode = fields["mode"]
    explicit_dates = re.findall(ISO_DATE, question)
    years = re.findall(r"\b\d{4}\b", re.sub(ISO_DATE, "", question))
    yearly = re.search(YEARLY_SCOPE, question, re.I)
    all_time = re.search(ALL_TIME_SCOPE, question, re.I)
    historical_trend = all_time and re.search(r"\btrends?\b", question, re.I)
    if mode == "year":
        return years == [f"{fields['year']:04d}"] and not (explicit_dates or yearly or all_time)
    if mode == "yearly":
        return not (years or explicit_dates) and bool(yearly or historical_trend)
    if mode == "all_time":
        return not (years or explicit_dates or yearly or historical_trend) and bool(all_time)
    if yearly or all_time or years:
        return False
    if mode == "comparison" and fields["start"] is None:
        # A default comparison cannot stand in for an unsupported requested period.
        return not re.search(r"\b(?:this|last|past|previous)\s+(?:\w+\s+)?(?:days?|weeks?|months?|years?)\b",
                             question, re.I)
    return True


def relative_dates(question, today):
    question = question.lower()
    periods = re.findall(RELATIVE_PERIOD, question)
    # These modifiers can turn a calendar period into a range endpoint.
    endpoint = rf"\b(?:since|before|after|until|through|to|from|between)\s+{RELATIVE_PERIOD}"
    if len(periods) != 1 or re.search(ISO_DATE, question) or re.search(endpoint, question):
        return None
    period = periods[0]
    if period == "today":
        start = end = today
    elif period == "yesterday":
        start = end = today - timedelta(days=1)
    elif period == "this week":
        start, end = monday(today), today
    elif period == "last week":
        end = monday(today) - timedelta(days=1)
        start = monday(end)
    elif period == "this month":
        start, end = today.replace(day=1), today
    else:
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    return start.isoformat(), end.isoformat()


def direct_reply(response):
    try:
        reply = json.loads(response.output_text, object_pairs_hook=unique_fields)
        if (not isinstance(reply, dict) or reply.keys() != {"kind", "message"}
                or reply["kind"] not in ("answer", "clarification", "unavailable")
                or not isinstance(reply["message"], str) or not reply["message"].strip()):
            raise ValueError
    except ValueError:
        raise FitnessError("OpenAI returned no usable reply.") from None
    print("General reply (no training evidence)" if reply["kind"] == "answer" else "Chat reply")
    print(reply["message"])
    return reply["kind"] == "clarification"


def answer(client, model, path, question, *, pending=None):
    if len(question) > MAX_QUESTION_CHARS:
        raise FitnessError(f"Keep questions to {MAX_QUESTION_CHARS} characters.")
    items = [{"role": "user", "content": question}]
    if pending and re.fullmatch(DATE_REPLY, question, re.IGNORECASE):
        items.insert(0, {"role": "user", "content": pending})
    else:
        pending = None
    resolved = None
    has_relative_period = re.search(RELATIVE_PERIOD, question, re.IGNORECASE)
    if has_relative_period:
        try:
            today = datetime.now(ZoneInfo("Asia/Singapore")).date()
        except ZoneInfoNotFoundError:
            raise FitnessError("Install Asia/Singapore timezone data to use relative dates.") from None
        resolved = relative_dates(question, today)
    first = request(client, model, items, allow_tool=True, resolved=resolved)
    calls = [item for item in first.output if item.type == "function_call"]
    if not calls:
        return (pending or question) if direct_reply(first) else None
    if len(calls) != 1:
        raise FitnessError("OpenAI requested more than one tool call.")
    call = calls[0]
    if call.name not in (TOOL["name"], RUNNING_TOOL["name"]) or not call.call_id:
        raise FitnessError("OpenAI requested an invalid tool call.")
    is_running = call.name == RUNNING_TOOL["name"]
    if is_running:
        today = today if has_relative_period else reporting_today()
        fields = running_arguments(call.arguments, today)
        start, end = fields["start"], fields["end"]
    else:
        start, end = tool_dates(call.arguments)
    if has_relative_period and resolved is None:
        print("Which date range should I use? Give both dates as YYYY-MM-DD.")
        return pending or question
    if resolved and (start, end) != resolved:
        raise FitnessError("OpenAI requested dates outside the resolved reporting range. Try explicit dates.")
    if is_running and not running_scope_matches(fields, question):
        raise FitnessError("The running report scope did not match the question. Try specifying the period.")
    if resolved is None and (not is_running or start is not None or re.search(ISO_DATE, question)):
        supplied_dates = tuple(re.findall(ISO_DATE, question))
        same_day = start == end and supplied_dates == (start,)
        if supplied_dates != (start, end) and not same_day:
            print("Which date range should I use? Give both dates as YYYY-MM-DD.")
            return pending or question
    report_name = "running trends" if is_running else "weekly"
    try:
        report = running_trends(path, **fields, today=today) if is_running else weekly_summary(path, start, end)
    except (FitnessError, sqlite3.Error, OSError, RuntimeError, ValueError):
        raise FitnessError(f"Cannot read the {report_name} report. Check the local database and schema.") from None
    try:
        evidence = json.dumps(report, allow_nan=False, separators=(",", ":"))
    except ValueError:
        raise FitnessError(f"The {report_name} report contains an unrepresentable value.") from None
    if len(evidence.encode("utf-8")) > MAX_RESULT_BYTES:
        raise FitnessError(f"The {report_name} report is too large for chat. Choose a shorter date range.")

    print("Deterministic evidence")
    print(json.dumps(report, indent=2, allow_nan=False))
    empty = report["status"] == "empty" if is_running else all(
        bounds is None for bounds in report["observed_dates"].values()
    )
    if empty:
        print("No stored runs in this report." if is_running else "No stored training records in this date range.")
        if is_running and fields["mode"] == "comparison":
            print("Try an explicit historical range if your recent running history is sparse.")
        return
    if is_running and "empty_comparison_period" in report["limitations"]:
        print("One comparison period has no stored runs. Try an explicit historical range.")
    print("Null metrics are unavailable. Coverage counts show how many records had usable inputs.")

    # Preserve the provider's item order while dropping draft prose.
    continuation = [
        *items,
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
        print("Keep private details out of your questions. Type /quit to exit.")
        pending = None
        while True:
            try:
                question = input("You> ").strip()
                if question.lower() in {"/quit", "quit"}:
                    return 0
                if question:
                    previous, pending = pending, None
                    pending = answer(client, model, path, question, pending=previous)
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
