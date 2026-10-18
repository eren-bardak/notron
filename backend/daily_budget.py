"""Shared, fail-closed reservations for the three-story economy batch.

Prices checked against official GPT-6 Luna/search documentation on 2026-10-16.
Amounts use integer millionths of a dollar. Uncertain calls keep their reservation.
"""
import json
import math
import os
import uuid
from types import SimpleNamespace


MAX_OUTPUT_TOKENS = 12000
MAX_TOOL_CALLS = 2
MAX_REQUEST_BYTES = 180_000
TEXT_RESERVATION = 70_000
SEARCH_RESERVATION = 900_000


class BudgetError(RuntimeError):
    pass


def ledger(db, operation, **values):
    run_id = os.environ.get("NOTRON_RUN_ID")
    if not run_id:
        raise BudgetError("Economy mode requires run_pipeline.py and its shared daily budget.")
    try:
        data = db.rpc("notron_daily_budget", {
            "p_operation": operation, "p_run_id": run_id, **values,
        }).execute().data
    except Exception as error:
        raise BudgetError("Shared budget ledger unavailable; no paid request authorized.") from error
    if not isinstance(data, dict) or data.get("ok") is not True:
        reason = data.get("reason", "ledger unavailable") if isinstance(data, dict) else "invalid ledger response"
        raise BudgetError(f"Daily batch stopped: {reason}")
    return data


def request_limits(options):
    """Validate the entire request before reserving or making a paid call."""
    options = dict(options)
    messages = options.get('input', '')
    if not isinstance(messages, str) and (not isinstance(messages, list) or any(
            not isinstance(message, dict) or not isinstance(message.get('content'), str)
            for message in messages)):
        raise BudgetError('The daily price envelope permits text messages only.')
    if options.get("model") != "gpt-6-luna":
        raise BudgetError("The daily price envelope is verified only for gpt-6-luna.")
    if any(key in options for key in ("previous_response_id", "conversation", "background", "stream", "extra_body", "extra_headers", "extra_query")):
        raise BudgetError("Stateful, background and custom requests are outside the daily price envelope.")
    tools = options.get("tools", [])
    if any(tool.get("type") != "web_search" for tool in tools):
        raise BudgetError("Only the priced web_search tool is allowed in daily mode.")
    schema = options.get("text_format")
    payload = {key: value for key, value in options.items() if key != "text_format"}
    if schema is not None:
        payload["schema"] = schema.model_json_schema()
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise BudgetError("Request exceeds the reviewed daily input limit.")
    # Standard service only; output includes hidden reasoning tokens.
    options["service_tier"] = "default"
    options["max_output_tokens"] = min(MAX_OUTPUT_TOKENS, int(options.get("max_output_tokens", MAX_OUTPUT_TOKENS)))
    if options["max_output_tokens"] <= 0:
        raise BudgetError("Invalid output limit.")
    if tools:
        options["max_tool_calls"] = MAX_TOOL_CALLS
        options["tools"] = [{"type": "web_search", "search_context_size": "low"} for _ in tools]
    return options, SEARCH_RESERVATION if tools else TEXT_RESERVATION


def usage_charge(response):
    """Overestimate model rates: long-context cache-write rate plus 10% premium."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int) or min(input_tokens, output_tokens) < 0:
        return None
    searches = sum(getattr(item, "type", None) == "web_search_call" for item in getattr(response, "output", []))
    # $0.25/$0.75 per million tokens; $0.01/search. Never assume cache discounts.
    return math.ceil((input_tokens * 0.25 + output_tokens * 0.75 + searches * 10_000) * 1.10)


class BudgetedResponses:
    def __init__(self, responses, db):
        self.responses = responses
        self.db = db

    def call(self, method, **options):
        options, reserved = request_limits(options)
        request_id = str(uuid.uuid4())
        ledger(self.db, "reserve", p_request_id=request_id, p_amount=reserved)
        # No exception releases money: timeouts and parse failures may have been billed.
        try:
            response = getattr(self.responses, method)(**options)
        except Exception as error:
            raise BudgetError(f"Paid request failed ({type(error).__name__}); reservation retained.") from error
        charged = usage_charge(response)
        if charged is None:
            raise BudgetError("Missing API usage; reservation retained and batch stopped.")
        ledger(self.db, "settle", p_request_id=request_id, p_amount=charged)
        return response

    def parse(self, **options):
        return self.call("parse", **options)

    def create(self, **options):
        return self.call("create", **options)


def budget_client(client, db):
    if os.environ.get("NOTRON_PIPELINE_MODE") != "economy":
        return client
    if not os.environ.get("NOTRON_RUN_ID"):
        raise BudgetError("Start economy mode through run_pipeline.py, not individual paid scripts.")
    return SimpleNamespace(responses=BudgetedResponses(client.responses, db))


def coverage_rank(event):
    return (-float(event.get("popularity_score") or 0), -int(event.get("source_count") or 0),
            -int(event.get("article_count") or 0), int(event["id"]))
