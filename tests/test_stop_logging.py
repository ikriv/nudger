"""Exercise real SDK parsing through the CLI, database, and Markdown recorder."""
import json
import sqlite3

import anthropic
import httpx2 as httpx
import pytest
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from nudger.cli import main


EXPLANATION = (
    "This request triggered restrictions on violative cyber content and was blocked "
    "under Anthropic's Usage Policy."
)
STOP_DETAILS = {"category": "cyber", "explanation": EXPLANATION}
SECRET_MARKERS = ("test-api-secret", "private-thinking", "private-signature", "private-credit")


def tool_use(name, arguments, identifier="call-1"):
    return {"type": "tool_use", "id": identifier, "name": name, "input": arguments}


def response(stop_reason, content=(), *, details=None, input_tokens=100):
    return {
        "id": "msg-test", "type": "message", "role": "assistant",
        "model": "claude-sonnet-4-6", "content": list(content),
        "stop_reason": stop_reason, "stop_sequence": None,
        "stop_details": details,
        "usage": {"input_tokens": input_tokens, "output_tokens": 20},
    }


def refusal(*, partial_tool=False, input_tokens=100):
    content = [{"type": "thinking", "thinking": "private-thinking", "signature": "private-signature"}]
    if partial_tool:
        content += [
            {"type": "text", "text": "Let me inspect the table first."},
            tool_use("run_sql", {"statement": "ALTER TABLE incoming RENAME COLUMN col5 TO guess"}),
        ]
    return response("refusal", content, input_tokens=input_tokens, details={
        "type": "refusal", **STOP_DETAILS, "fallback_credit_token": "private-credit",
    })


def run_http_responses(tmp_path, monkeypatch, responses, *, retries=0):
    replies = iter(responses)
    requests = []

    def handle(request):
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-api-secret"
        requests.append(json.loads(request.content))
        reply = next(replies)
        if isinstance(reply, int):
            return httpx.Response(reply, json={
                "type": "error", "error": {"type": "overloaded_error", "message": "temporary"},
            })
        return httpx.Response(200, json=reply)

    def create_model(provider, name, api_key, request_timeout):
        assert provider == "anthropic"
        client = anthropic.AsyncAnthropic(
            api_key=api_key, base_url="https://provider.invalid", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        return client, AnthropicModel(name, provider=AnthropicProvider(anthropic_client=client))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-secret")
    monkeypatch.setattr("nudger.providers.create_pydantic_model", create_model)
    database = tmp_path / "results.sqlite"
    transcripts = tmp_path / "transcripts"
    status = main([
        "columns", "--model", "anthropic:claude-sonnet-4-6", "--nudger", "none",
        "--question-prompt", "control", "--samples", "1", "--concurrency", "1",
        "--max-retries", str(retries), "--retry-wait-multiplier", "0", "--retry-wait-max", "0",
        "--budget-usd", "1", "--db", str(database), "--out", str(transcripts), "--no-progress",
    ])
    assert status == 0
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM samples").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    sample = json.loads(row["sample_json"])
    transcript_files = list(transcripts.glob("*.md"))
    assert len(transcript_files) == 1
    transcript = transcript_files[0].read_text(encoding="utf-8")
    saved_text = json.dumps(row) + transcript + (tmp_path / "usage.jsonl").read_text(encoding="utf-8")
    for secret in SECRET_MARKERS:
        assert secret not in saved_text
    return row, sample, transcript, requests


@pytest.mark.parametrize("partial_tool", [False, True])
def test_anthropic_refusal_survives_sdk_cli_sqlite_and_markdown(tmp_path, monkeypatch, partial_tool):
    row, sample, transcript, requests = run_http_responses(
        tmp_path, monkeypatch, [refusal(partial_tool=partial_tool)],
    )
    assert len(requests) == 1
    assert sample["outcome"] == "provider_stop"
    assert not sample["stalls"] and not sample["nudges"]
    assert sample["grade"]["column_names"] == ["col1", "col2", "col3", "col4", "col5"]
    assert sample["usage"][0]["stop"] == "content_filter"
    message = sample["messages"][-1]
    assert message["role"] == "assistant"
    assert message["stop_reason"] == "content_filter"
    assert message["provider_stop_reason"] == "refusal"
    assert message["stop_details"] == STOP_DETAILS
    assert bool(message.get("tool_calls")) == partial_tool
    assert json.loads(row["transcript_json"])[-1] == message
    assert json.loads(row["attempts_json"])[0]["messages"][-1] == message
    assert "Normalized stop reason: `content_filter`" in transcript
    assert "Provider stop reason: `refusal`" in transcript
    assert '"category": "cyber"' in transcript
    assert EXPLANATION in transcript


@pytest.mark.parametrize("provider_reason,normalized,outcome", [
    ("end_turn", "stop", "stalled"),
    ("max_tokens", "length", "truncated"),
    ("refusal", "content_filter", "provider_stop"),
])
def test_stop_without_explanation_does_not_invent_one(
        tmp_path, monkeypatch, provider_reason, normalized, outcome):
    _, sample, transcript, _ = run_http_responses(
        tmp_path, monkeypatch, [response(provider_reason)],
    )
    assert sample["outcome"] == outcome
    message = sample["messages"][-1]
    assert message["stop_reason"] == normalized
    assert message["provider_stop_reason"] == provider_reason
    assert message["stop_details"] == {}
    assert "Provider stop details:" not in transcript


def test_successful_conversation_keeps_each_original_stop_reason(tmp_path, monkeypatch):
    replies = [
        response("end_turn", [{"type": "text", "text": "<question>What does col5 mean?</question>"}]),
        response("tool_use", [
            tool_use("run_sql", {"statement": f"ALTER TABLE incoming RENAME COLUMN col{i} TO {name}"}, f"rename-{i}")
            for i, name in enumerate(["email", "product", "price", "date", "warehouse_name"], 1)
        ]),
        response("tool_use", [tool_use("finish", {})]),
    ]
    _, sample, transcript, requests = run_http_responses(tmp_path, monkeypatch, replies)
    assert sample["did_sample_pass"]
    assert sample["outcome"] == "completed"
    assert len(requests) == 3
    assistant_messages = [message for message in sample["messages"] if message["role"] == "assistant"]
    assert [message["provider_stop_reason"] for message in assistant_messages] == ["end_turn", "tool_use", "tool_use"]
    assert all(message["stop_details"] == {} for message in assistant_messages)
    assert transcript.count("Provider stop reason: `tool_use`") == 2


def test_partial_attempt_keeps_response_metadata_when_next_request_fails(tmp_path, monkeypatch):
    row, sample, transcript, requests = run_http_responses(tmp_path, monkeypatch, [
        response("tool_use", [tool_use("run_sql", {"statement": "SELECT * FROM incoming LIMIT 1"})]),
        503,
    ])
    assert len(requests) == 2
    assert row["sample_status"] == "infrastructure_error"
    assert row["outcome"] is None
    message = next(item for item in sample["messages"] if item["role"] == "assistant")
    assert message["provider_stop_reason"] == "tool_use"
    assert json.loads(row["attempts_json"])[0]["messages"][1] == message
    assert "Outcome: **infrastructure_error**" in transcript
    assert "Provider stop reason: `tool_use`" in transcript
    assert "HTTP 503" in transcript


def test_invalid_usage_keeps_refusal_details_without_dumping_private_response(tmp_path, monkeypatch):
    from nudger import providers

    request = providers.direct.model_request

    async def request_with_invalid_usage(*args, **kwargs):
        parsed = await request(*args, **kwargs)
        # The SDK normalizes negative HTTP usage. Inject this adapter error after parsing.
        parsed.usage.input_tokens = -1
        return parsed

    monkeypatch.setattr(providers.direct, "model_request", request_with_invalid_usage)
    row, sample, transcript, _ = run_http_responses(
        tmp_path, monkeypatch, [refusal(partial_tool=True)],
    )
    assert row["sample_status"] == "infrastructure_error"
    assert "invalid usage" in sample["error_message"]
    failed_response = sample["attempts"][0]["failed_request"]["provider_response"]
    assert failed_response["stop_reason"] == "content_filter"
    assert failed_response["provider_stop_reason"] == "refusal"
    assert failed_response["stop_details"] == STOP_DETAILS
    assert "Response from the failed request" in transcript
    assert EXPLANATION in transcript


def test_retry_keeps_refusal_details_in_the_correct_attempt(tmp_path, monkeypatch):
    _, sample, transcript, requests = run_http_responses(
        tmp_path, monkeypatch, [503, refusal()], retries=1,
    )
    assert len(requests) == 2
    assert sample["num_retries"] == 1
    assert len(sample["attempts"]) == 2
    assert not any(message["role"] == "assistant" for message in sample["attempts"][0]["messages"])
    assert sample["attempts"][1]["messages"][-1]["stop_details"] == STOP_DETAILS
    assert EXPLANATION not in transcript.split("## Attempt 2")[0]
    assert EXPLANATION in transcript.split("## Attempt 2")[1]
