import asyncio

import pytest
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.usage import RequestUsage

from nudger.providers import (
    APIModel,
    MODEL_PRICES_FILE,
    NVIDIA_BASE_URL,
    ProviderError,
    load_model_prices,
    model_prices,
)
from nudger.budget import Budget, BudgetExceeded
from nudger.runner import call, tool


GET_ORDER = tool("get_order", "Look up an order.", {"reference": {"type": "string"}})


def test_requests_and_client_shutdown_share_one_event_loop(tmp_path, monkeypatch):
    loops = []
    response = ModelResponse(
        parts=[TextPart("Done")],
        usage=RequestUsage(input_tokens=1, output_tokens=1),
        model_name="fake",
        finish_reason="stop",
    )

    async def request(*args, **kwargs):
        loops.append(asyncio.get_running_loop())
        return response

    class Client:
        async def close(self):
            loops.append(asyncio.get_running_loop())

    monkeypatch.setattr("nudger.providers.direct.model_request", request)
    with Budget(tmp_path, 1) as budget:
        model = APIModel(
            "openai:gpt-5-mini",
            budget,
            pydantic_model=FunctionModel(lambda messages, info: response, model_name="fake"),
        )
        model.client = Client()
        model.complete("system", [], [{"role": "user", "content": "first"}])
        model.complete("system", [], [{"role": "user", "content": "second"}])
        model.close()

    assert len(loops) == 3
    assert loops[0] is loops[1] is loops[2]


def test_model_prices_come_from_packaged_catalog(tmp_path):
    assert MODEL_PRICES_FILE.name == "model_prices.toml"
    assert load_model_prices()["openai:gpt-5-mini"] == (0.25, 2.0)
    assert load_model_prices()["nvidia:nvidia/nemotron-3-ultra-550b-a55b"] == (0.0, 0.0)

    custom_catalog = tmp_path / "prices.toml"
    custom_catalog.write_text(
        '[models."openai:test-model"]\n'
        'input_usd_per_million_tokens = 1.25\n'
        'output_usd_per_million_tokens = 4.5\n',
        encoding="utf-8",
    )
    assert model_prices("openai:test-model", custom_catalog) == (1.25, 4.5)


def test_unknown_model_price_directs_user_to_catalog(tmp_path):
    custom_catalog = tmp_path / "prices.toml"
    custom_catalog.write_text("[models]\n", encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        model_prices("openai:unlisted", custom_catalog)
    message = str(caught.value)
    assert "--budget-usd" in message
    assert "openai:unlisted" in message
    assert str(custom_catalog) in message


def test_budget_persists_spend_and_unknown_reservations(tmp_path):
    with Budget(tmp_path, 0.1) as budget:
        one = budget.reserve({}, 100, (1, 5))
        budget.settle(one, 0.01, 10, 10)
        budget.reserve({}, 100, (1, 5))
        charged = budget.charged()
        assert charged > 0.01
        with pytest.raises(BudgetExceeded):
            budget.reserve({}, 100000, (1, 5))
    with Budget(tmp_path, 0.1) as again:
        assert again.charged() == charged


def test_second_process_cannot_share_budget(tmp_path):
    with Budget(tmp_path, 1):
        with pytest.raises(BudgetExceeded):
            with Budget(tmp_path, 1):
                pass


def test_pydantic_model_api_normalizes_tools_usage_and_history(tmp_path):
    seen = []
    responses = [
        ModelResponse(
            parts=[ToolCallPart("get_order", {"reference": "R-210"}, "lookup")],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
            model_name="served-model",
            finish_reason="tool_call",
        ),
        ModelResponse(
            parts=[TextPart("Done")],
            usage=RequestUsage(input_tokens=120, output_tokens=10),
            model_name="served-model",
            finish_reason="stop",
        ),
    ]

    def respond(messages, info):
        seen.append((list(messages), info))
        return responses.pop(0)

    with Budget(tmp_path, 1) as budget:
        model = APIModel(
            "openai:gpt-5-mini", budget,
            pydantic_model=FunctionModel(respond, model_name="fake"),
        )
        transcript = [{"role": "user", "content": "hello"}]
        first = model.complete("system", [GET_ORDER], transcript)
        transcript += [
            {"role": "assistant", "content": first.text, "tool_calls": first.tool_calls},
            {"role": "tool", "tool_call_id": "lookup", "name": "get_order",
             "content": '{"reference": "R-210"}'},
        ]
        second = model.complete("system", [GET_ORDER], transcript)

        assert first.tool_calls[0]["id"] == "lookup"
        assert first.tool_calls[0]["function"]["name"] == "get_order"
        assert first.tool_calls[0]["function"]["arguments"].replace(" ", "") == '{"reference":"R-210"}'
        assert second.text == "Done" and second.served_model_name == "fake"
        assert seen[0][1].function_tools[0].name == "get_order"
        assert seen[0][1].model_settings["max_tokens"] == 8192
        assert seen[0][1].model_settings["timeout"] == 120.0
        last_request = seen[1][0][-1]
        assert isinstance(last_request, ModelRequest)
        assert any(isinstance(part, ToolReturnPart) and part.tool_name == "get_order"
                   for part in last_request.parts)
        assert budget.charged() == pytest.approx((220 * 0.25 + 30 * 2) / 1_000_000)
        assert "settled" in budget.journal.read_text()


@pytest.mark.parametrize("label,expected_thinking,expected_cost", [
    ("openai:gpt-5-mini", "medium", 0.000065),
    ("anthropic:claude-sonnet-4-6", False, 0.0006),
    ("nvidia:nvidia/nemotron-3-ultra-550b-a55b", None, 0.0),
    ("litellm:gpt-5-mini", "medium", 0.000065),
    ("litellm:bedrock-claude-sonnet-4-6", None, 0.0006),
    ("litellm:bedrock-claude-opus-5-5", None, 0.0008),
    ("litellm:gpt-5.6-sol", "medium", 0.0008),
    ("anthropic:claude-fable-5-1", None, 0.002),
    ("anthropic:claude-opus-5-5", None, 0.0008),
])
def test_reasoning_setting_is_sent_to_pydantic_model_request(
        tmp_path, monkeypatch, label, expected_thinking, expected_cost):
    seen_settings = []
    response = ModelResponse(
            parts=[TextPart("<question>What is col5?</question>")],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
            model_name="claude-sonnet-4-6",
            finish_reason="stop",
        )

    async def request(model, messages, **kwargs):
        seen_settings.append(kwargs["model_settings"])
        return response

    monkeypatch.setattr("nudger.providers.direct.model_request", request)

    with Budget(tmp_path, 1) as budget:
        model = APIModel(
            label, budget,
            pydantic_model=FunctionModel(lambda messages, info: response, model_name="fake"),
        )
        reply = model.complete("system", [], [{"role": "user", "content": "hello"}])
        assert reply.text.startswith("<question>")
        if expected_thinking is None:
            assert "thinking" not in seen_settings[0]
        else:
            assert seen_settings[0]["thinking"] == expected_thinking
        assert budget.charged() == pytest.approx(expected_cost)


@pytest.mark.parametrize("failure,expected", [
    (ModelHTTPError(429, "test", {"private": "test-secret"}), "HTTP 429"),
    (ModelAPIError("test", "private test-secret"), "transport failure"),
])
def test_provider_errors_are_not_retried_or_exposed(tmp_path, failure, expected):
    num_requests = 0

    def respond(messages, info):
        nonlocal num_requests
        num_requests += 1
        raise failure

    with Budget(tmp_path, 1) as budget:
        model = APIModel(
            "openai:gpt-5-mini", budget,
            pydantic_model=FunctionModel(respond, model_name="fake"),
        )
        with pytest.raises(ProviderError) as caught:
            model.complete("system", [], [{"role": "user", "content": "private user text"}])
        assert num_requests == 1 and budget.charged() > 0
        assert expected in str(caught.value)
        assert "test-secret" not in str(caught.value) and "private user text" not in str(caught.value)
        assert caught.value.request_audit["estimated_cost_usd"] > 0
        assert caught.value.request_audit["reservation_id"]
        assert "settled" not in budget.journal.read_text()


def test_invalid_usage_keeps_reservation(tmp_path):
    response = ModelResponse(
        parts=[TextPart("Done")],
        usage=RequestUsage(input_tokens=-1, output_tokens=2),
        model_name="test",
    )
    with Budget(tmp_path, 1) as budget:
        model = APIModel(
            "openai:gpt-5-mini", budget,
            pydantic_model=FunctionModel(lambda messages, info: response, model_name="fake"),
        )
        with pytest.raises(ProviderError):
            model.complete("system", [], [{"role": "user", "content": "hello"}])
        assert budget.charged() > 0 and "settled" not in budget.journal.read_text()


@pytest.mark.parametrize("label,variable,expected_type", [
    ("openai:gpt-5-mini", "OPENAI_API_KEY", OpenAIChatModel),
    ("anthropic:claude-sonnet-4-6", "ANTHROPIC_API_KEY", AnthropicModel),
    ("nvidia:nvidia/nemotron-3-ultra-550b-a55b", "NVIDIA_API_KEY", OpenAIChatModel),
    ("litellm:gpt-5-mini", "LITELLM_API_KEY", OpenAIChatModel),
])
def test_live_configuration_builds_pydantic_model_with_sdk_retries_disabled(
        tmp_path, monkeypatch, label, variable, expected_type):
    monkeypatch.setenv(variable, "unit-test-secret")
    if label.startswith("litellm:"):
        monkeypatch.setenv("LITELLM_BASE_URL", "https://proxy.example.test/v1")
    with Budget(tmp_path, 1) as budget:
        model = APIModel(label, budget)
        try:
            assert isinstance(model.model, expected_type)
            assert model.client.max_retries == 0
            if label.startswith("nvidia:"):
                assert str(model.client.base_url).rstrip("/") == NVIDIA_BASE_URL
            elif label.startswith("litellm:"):
                assert str(model.client.base_url).rstrip("/") == "https://proxy.example.test/v1"
        finally:
            model.close()


def test_litellm_requires_an_explicit_proxy_url(monkeypatch):
    from nudger.providers import create_pydantic_model

    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="LITELLM_BASE_URL"):
        create_pydantic_model("litellm", "gpt-5-mini", "unit-test-secret")


def test_user_prompt_is_a_pydantic_message(tmp_path):
    seen = []

    def respond(messages, info):
        seen.extend(messages)
        return ModelResponse(parts=[TextPart("Done")], usage=RequestUsage(input_tokens=1, output_tokens=1))

    with Budget(tmp_path, 1) as budget:
        APIModel("openai:gpt-5-mini", budget,
                 pydantic_model=FunctionModel(respond)).complete(
                     "system", [], [{"role": "user", "content": "hello"}])
    assert any(isinstance(part, UserPromptPart) and part.content == "hello"
               for message in seen if isinstance(message, ModelRequest) for part in message.parts)
