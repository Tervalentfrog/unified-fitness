"""Bounded OpenAI commentary on the local weekly report."""

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .analytics import (
    DISTANCE_BANDS, PERIOD_MODES, RECORD_METRICS, RECORD_MODES, monday, report_bounds, report_dates,
    reporting_today, running_records, running_trends, strength_activity, validate_record_options, weekly_summary,
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
PERIOD_PROPERTIES = {
    "mode": {"type": "string", "enum": list(PERIOD_MODES)},
    "start": {"type": ["string", "null"], "description": "Inclusive ISO start for range or comparison."},
    "end": {"type": ["string", "null"], "description": "Inclusive ISO end for range or comparison."},
    "year": {"type": ["integer", "null"], "description": "Calendar year for year mode only."},
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
        "properties": PERIOD_PROPERTIES,
        "required": list(PERIOD_PROPERTIES),
        "additionalProperties": False,
    },
}
STRENGTH_TOOL = {
    "type": "function",
    "name": "get_strength_progress",
    "description": (
        "Read recorded strength sets, known repetitions, and distinct training dates, optionally "
        "for one exact exercise name from the question. Use null exercise only for overall strength. "
        "Supports comparison, range, year, yearly, and all_time. For a named exercise only, "
        "also returns maximum load, kg × reps, and estimated 1RM when verified external kg loads exist."
    ),
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {**PERIOD_PROPERTIES, "exercise": {"type": ["string", "null"]}},
        "required": [*PERIOD_PROPERTIES, "exercise"],
        "additionalProperties": False,
    },
}
RECORD_PROPERTIES = {
    **PERIOD_PROPERTIES,
    "mode": {"type": "string", "enum": list(RECORD_MODES)},
    "metric": {"type": "string", "enum": list(RECORD_METRICS)},
    "distance_band": {"enum": [*DISTANCE_BANDS, None], "type": ["string", "null"]},
}
RECORD_TOOL = {
    "type": "function",
    "name": "get_running_records",
    "description": (
        "Find fastest whole-run average moving pace in a user-selected distance band, or count runs "
        "by weekday or Singapore time of day. Ask for the missing band or pattern dimension. "
        "Default to all_time when no period is requested. No splits, finish-time records, or seasons."
    ),
    "strict": True,
    "parameters": {
        "type": "object", "properties": RECORD_PROPERTIES,
        "required": list(RECORD_PROPERTIES), "additionalProperties": False,
    },
}
TOOLS = [TOOL, RUNNING_TOOL, STRENGTH_TOOL, RECORD_TOOL]
INSTRUCTIONS = (
    "Answer general questions directly. Never make claims about the user's recorded training "
    "without tool evidence. If the question needs a date range and it is unclear, "
    "ask one focused clarification; do not guess dates. Use locally resolved dates when supplied, "
    "otherwise require both dates in YYYY-MM-DD form for explicit ranges. Running and strength reports can use "
    "an explicitly requested year, yearly or all-time scope, or the default comparison for change questions. "
    "In running comparisons use pace_direction and eligible distance bands; overall pace is descriptive. "
    "For exercise-specific strength questions use the exact exercise wording from the user. "
    "Strength sets, reps and recorded days do not establish strength gains or load-based volume. "
    "Use only non-null load metrics and eligible load deltas. Label volume as a subtotal when "
    "volume_is_subtotal is true. Explain missing coverage. "
    "Estimated 1RM uses the Epley formula on 2–10 reps with unknown effort and is not a measured maximum. "
    "Use get_running_records for fastest moving pace or common run periods, asking which distance band "
    "(under 5 km, 5 to under 10 km, or 10 km or more) or pattern (weekday or time of day) if unclear. "
    "Explain that exact-distance finish times, splits, and seasonal patterns are unavailable. "
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
BAND_PHRASES = {
    "under_5_km": r"\b(?:under|below|less than)\s+5\s*km\b",
    "5_to_under_10_km": r"(?<![\w.])5\s*(?:km\s*)?(?:to|[-–])\s*(?:under\s+)?10\s*km\b",
    "10_km_or_more": r"(?:(?<![\w.])10\s*km\s*(?:or more\b|and up\b|\+)|\bat least\s+10\s*km\b)",
}
RECORD_REPLY = r"(?:weekday|day of (?:the )?week|time of day|" + "|".join(BAND_PHRASES.values()) + r")[.!]?"


def request(client, model, items, *, allow_tool, resolved=None):
    instructions = INSTRUCTIONS
    options = {}
    if allow_tool:
        options["text"] = {"format": REPLY_FORMAT}
        instructions += (
            " If no tool is called, classify the reply as answer for general information, "
            "clarification for missing details, or unavailable for unsupported analysis."
        )
    if resolved:
        instructions += f" The locally resolved reporting range is {resolved[0]} through {resolved[1]}."
    response = client.responses.create(
        model=model, input=items, instructions=instructions, tools=TOOLS,
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


def period_arguments(arguments, today, *, tool):
    try:
        if not isinstance(arguments, str) or len(arguments) > (2048 if tool is STRENGTH_TOOL else 256):
            raise ValueError
        fields = json.loads(arguments, object_pairs_hook=unique_fields)
        if not isinstance(fields, dict) or fields.keys() != tool["parameters"]["properties"].keys():
            raise ValueError
    except ValueError:
        raise FitnessError("OpenAI requested invalid report arguments.") from None
    report_bounds(**{name: fields[name] for name in PERIOD_PROPERTIES}, today=today)
    return fields


def period_scope_matches(fields, question, *, default_all_time=False):
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
        relative = re.search(r"\b(?:this|last|past|previous)\s+(?:\w+\s+)?(?:days?|weeks?|months?|years?)\b",
                             question, re.I)
        return not (years or explicit_dates or yearly or historical_trend or relative) and (
            default_all_time or bool(all_time)
        )
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
    record_reply = pending and re.fullmatch(RECORD_REPLY, question, re.IGNORECASE)
    if pending and (record_reply or re.fullmatch(DATE_REPLY, question, re.IGNORECASE)):
        items.insert(0, {"role": "user", "content": pending})
    else:
        pending = None
    context = "\n".join(item["content"] for item in items)
    clarification_context = context if len(context) <= MAX_QUESTION_CHARS else None
    resolved = None
    scope_text = pending if record_reply else question
    has_relative_period = re.search(RELATIVE_PERIOD, scope_text, re.IGNORECASE)
    if has_relative_period:
        try:
            today = datetime.now(ZoneInfo("Asia/Singapore")).date()
        except ZoneInfoNotFoundError:
            raise FitnessError("Install Asia/Singapore timezone data to use relative dates.") from None
        resolved = relative_dates(scope_text, today)
    first = request(client, model, items, allow_tool=True, resolved=resolved)
    calls = [item for item in first.output if item.type == "function_call"]
    if not calls:
        return clarification_context if direct_reply(first) else None
    if len(calls) != 1:
        raise FitnessError("OpenAI requested more than one tool call.")
    call = calls[0]
    tool = next((candidate for candidate in TOOLS if candidate["name"] == call.name), None)
    if tool is None or not call.call_id:
        raise FitnessError("OpenAI requested an invalid tool call.")
    is_running = tool is RUNNING_TOOL
    is_strength = tool is STRENGTH_TOOL
    is_records = tool is RECORD_TOOL
    uses_periods = tool is not TOOL
    if uses_periods:
        today = today if has_relative_period else reporting_today()
        fields = period_arguments(call.arguments, today, tool=tool)
        start, end = fields["start"], fields["end"]
    else:
        start, end = tool_dates(call.arguments)
    if has_relative_period and resolved is None:
        print("Which date range should I use? Give both dates as YYYY-MM-DD.")
        return pending or question
    if resolved and (start, end) != resolved:
        raise FitnessError("OpenAI requested dates outside the resolved reporting range. Try explicit dates.")
    if uses_periods and not period_scope_matches(fields, scope_text, default_all_time=is_records):
        raise FitnessError("The report scope did not match the question. Try specifying the period.")
    if resolved is None and (not uses_periods or start is not None or re.search(ISO_DATE, scope_text)):
        supplied_dates = tuple(re.findall(ISO_DATE, scope_text))
        same_day = start == end and supplied_dates == (start,)
        if supplied_dates != (start, end) and not same_day:
            print("Which date range should I use? Give both dates as YYYY-MM-DD.")
            return pending or question
    report_name = {
        TOOL["name"]: "weekly", RUNNING_TOOL["name"]: "running trends",
        STRENGTH_TOOL["name"]: "strength activity", RECORD_TOOL["name"]: "running records",
    }[call.name]
    if is_records:
        if fields["metric"] == "fastest_pace" and fields["distance_band"] is None:
            print("Which distance band: under 5 km, 5 to under 10 km, or 10 km or more?")
            return clarification_context
        validate_record_options(fields["metric"], fields["mode"], fields["distance_band"])
        user_text = " ".join(item["content"] for item in items)
        if fields["metric"] == "fastest_pace":
            bands = [band for band, phrase in BAND_PHRASES.items() if re.search(phrase, user_text, re.I)]
            if bands != [fields["distance_band"]]:
                print("Which distance band: under 5 km, 5 to under 10 km, or 10 km or more?")
                return clarification_context
        else:
            weekday = bool(re.search(r"\b(?:weekdays?|day of (?:the )?week)\b", user_text, re.I))
            clock = bool(re.search(r"\b(?:time of day|what time|morning|afternoon|evening)\b", user_text, re.I))
            if weekday == clock or weekday != (fields["metric"] == "weekday"):
                print("Do you mean weekday or time of day?")
                return clarification_context
    if is_strength and fields["exercise"] is not None:
        exercise = fields["exercise"]
        user_text = " ".join(item["content"] for item in items).casefold()
        if (not isinstance(exercise, str) or not exercise.strip() or len(exercise) > 200
                or not re.search(rf"(?<!\w){re.escape(exercise.strip().casefold())}(?!\w)", user_text)):
            raise FitnessError("Use the full exercise name from your question.")
    try:
        if uses_periods:
            calculate = {RUNNING_TOOL["name"]: running_trends, STRENGTH_TOOL["name"]: strength_activity,
                         RECORD_TOOL["name"]: running_records}[call.name]
            report = calculate(path, **fields, today=today)
        else:
            report = weekly_summary(path, start, end)
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
    if is_strength and report["status"] == "exercise_not_found":
        print("No exercise matched. Check the full name in your local strength summary.")
        return
    if is_strength and report["status"] == "exercise_ambiguous":
        print("Multiple exercises share that name. The report cannot select one by name.")
        return
    empty = report["status"] == "empty" if uses_periods else all(
        bounds is None for bounds in report["observed_dates"].values()
    )
    if empty:
        print("No stored runs in this report." if is_running or is_records
              else "No stored training records in this date range.")
        if is_running and fields["mode"] == "comparison":
            print("Try an explicit historical range if your recent running history is sparse.")
        return
    if is_records and report["status"] == "unavailable":
        print("No stored runs have usable evidence for this record or pattern.")
        return
    if (is_running or is_strength) and "empty_comparison_period" in report["limitations"]:
        print("One comparison period has no stored records. Try an explicit historical range.")
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
