"""PydanticAI model adapters with explicit budgeting and no automatic retries."""
from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path
import tomllib

import anthropic
import openai
from pydantic_ai import direct
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from .errors import ProviderError
from .runner import Reply

MODEL_PRICES_FILE = Path(__file__).with_name("model_prices.toml")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
ANTHROPIC_DEFAULT_THINKING_MODELS = {
    "claude-fable-5", "claude-fable-5-1", "claude-opus-5-5",
}


def load_model_prices(path: Path = MODEL_PRICES_FILE) -> dict[str, tuple[float, float]]:
    """Load input/output USD per million tokens from the editable catalog."""
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Cannot read model prices from {path}: {exc}") from None
    models = document.get("models")
    if not isinstance(models, dict):
        raise ValueError(f"Model price file {path} must contain a [models] table.")

    prices: dict[str, tuple[float, float]] = {}
    for model_name, values in models.items():
        if not isinstance(values, dict):
            raise ValueError(f"Price entry for {model_name!r} in {path} must be a table.")
        input_price = values.get("input_usd_per_million_tokens")
        output_price = values.get("output_usd_per_million_tokens")
        if (type(input_price) not in {int, float} or not math.isfinite(input_price)
                or input_price < 0):
            raise ValueError(f"Input price for {model_name!r} in {path} cannot be negative.")
        if (type(output_price) not in {int, float} or not math.isfinite(output_price)
                or output_price < 0):
            raise ValueError(f"Output price for {model_name!r} in {path} cannot be negative.")
        prices[model_name] = (float(input_price), float(output_price))
    return prices


def model_prices(model_name: str, path: Path = MODEL_PRICES_FILE) -> tuple[float, float]:
    try:
        return load_model_prices(path)[model_name]
    except KeyError:
        raise ValueError(
            f"No price is configured for {model_name!r}, so --budget-usd cannot estimate "
            f"request cost. Add its input and output prices to {path}."
        ) from None


def get_api_key_variable(provider: str) -> str:
    variables = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "litellm": "LITELLM_API_KEY",
    }
    return variables[provider]


def create_pydantic_model(
    provider: str, model_name: str, api_key: str, request_timeout: float = 120.0
):
    if provider == "anthropic":
        client = anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=0, timeout=request_timeout
        )
        model = AnthropicModel(
            model_name,
            provider=AnthropicProvider(anthropic_client=client),
        )
        return client, model

    client_arguments = {
        "api_key": api_key, "max_retries": 0, "timeout": request_timeout,
    }
    if provider == "nvidia":
        client_arguments["base_url"] = NVIDIA_BASE_URL
    elif provider == "litellm":
        base_url = os.environ.get("LITELLM_BASE_URL", "").strip()
        if not base_url:
            raise ValueError("Set LITELLM_BASE_URL for the LiteLLM proxy.")
        client_arguments["base_url"] = base_url
    client = openai.AsyncOpenAI(**client_arguments)
    model = OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(openai_client=client),
    )
    return client, model


def _model_messages(system, messages, responses):
    """Convert the visible transcript while retaining provider-specific response parts."""
    output: list[ModelMessage] = []
    request_parts: list[ModelRequestPart] = [SystemPromptPart(system)]
    response_index = 0
    tool_names = {}

    def flush_request():
        nonlocal request_parts
        if request_parts:
            output.append(ModelRequest(parts=request_parts))
            request_parts = []

    for message in messages:
        role = message["role"]
        if role == "assistant":
            flush_request()
            response = responses[response_index]
            response_index += 1
            output.append(response)
            for part in response.parts:
                if isinstance(part, ToolCallPart):
                    tool_names[part.tool_call_id] = part.tool_name
        elif role == "tool":
            request_parts.append(ToolReturnPart(
                message.get("name") or tool_names[message["tool_call_id"]],
                message["content"],
                message["tool_call_id"],
            ))
        elif role == "user":
            request_parts.append(UserPromptPart(message["content"]))
        else:
            raise ValueError(f"Unsupported transcript role: {role}")
    flush_request()
    return output


def _tool_definitions(tools):
    return [ToolDefinition(
        name=tool["function"]["name"],
        description=tool["function"]["description"],
        parameters_json_schema=tool["function"]["parameters"],
    ) for tool in tools]


def _stop_metadata(response):
    """Keep public stop diagnostics, not arbitrary provider or thinking metadata.

    PydanticAI exposes Anthropic's stop_details.category/explanation as
    refusal_category/refusal, and the original stop_reason as finish_reason.
    """
    details = response.provider_details or {}
    provider_stop_reason = details.get("finish_reason")
    stop_details = {
        target: details[source]
        for source, target in (("refusal_category", "category"), ("refusal", "explanation"))
        if isinstance(details.get(source), str)
    }
    return {
        "provider_stop_reason": (
            provider_stop_reason if isinstance(provider_stop_reason, str) else None
        ),
        "stop_details": stop_details,
    }


class APIModel:
    def __init__(self, model, budget, *, max_output=8192, reasoning="medium",
                 request_timeout=120.0,
                 pydantic_model=None, prices_path: Path = MODEL_PRICES_FILE) -> None:
        self.label = model
        self.provider, separator, self.name = model.partition(":")
        supported_providers = {"openai", "anthropic", "nvidia", "litellm"}
        if not separator or self.provider not in supported_providers or not self.name:
            raise ValueError("Use openai:<model>, anthropic:<model>, nvidia:<model>, or litellm:<model>.")
        self.prices = model_prices(model, prices_path)
        self.budget = budget
        self.max_output = max_output
        self.reasoning = reasoning
        self.request_timeout = request_timeout
        self.responses: list[ModelResponse] = []
        self.async_runner = asyncio.Runner()
        self.client = None
        if pydantic_model is not None:
            self.model = pydantic_model
            return

        variable = get_api_key_variable(self.provider)
        key = os.environ.get(variable)
        if not key:
            raise ValueError(f"Set {variable}.")
        self.client, self.model = create_pydantic_model(
            self.provider, self.name, key, request_timeout
        )

    def close(self):
        try:
            if self.client is not None:
                self.async_runner.run(self.client.close())
        finally:
            self.async_runner.close()

    def complete(self, system, tools, messages):
        model_messages = _model_messages(system, messages, self.responses)
        tool_definitions = _tool_definitions(tools)
        settings: ModelSettings = {
            "max_tokens": self.max_output, "timeout": self.request_timeout,
        }
        uses_openai_reasoning = self.provider == "openai" or (
            self.provider == "litellm" and self.name.startswith("gpt-")
        )
        if uses_openai_reasoning and self.reasoning != "omit":
            settings["thinking"] = self.reasoning
        elif self.provider == "anthropic" and self.name not in ANTHROPIC_DEFAULT_THINKING_MODELS:
            settings["thinking"] = False
        request_parameters = ModelRequestParameters(
            function_tools=tool_definitions,
            allow_text_output=True,
        )
        payload = {
            "model": self.label,
            "messages": ModelMessagesTypeAdapter.dump_python(model_messages, mode="json"),
            "tools": tools,
            "max_output": self.max_output,
            "request_timeout_seconds": self.request_timeout,
            "reasoning": (
                (self.reasoning if self.reasoning != "omit" else "omitted")
                if uses_openai_reasoning
                else ("disabled" if settings.get("thinking") is False else "omitted")
            ),
        }
        reservation = self.budget.reserve(payload, self.max_output, self.prices)
        request_audit = {
            "reservation_id": reservation.identifier,
            "estimated_cost_usd": reservation.estimated_cost_usd,
            "input_tokens": None,
            "output_tokens": None,
            "served_model_name": None,
        }
        try:
            response = self.async_runner.run(direct.model_request(
                self.model,
                model_messages,
                model_settings=settings,
                model_request_parameters=request_parameters,
                instrument=False,
            ))
        except ModelHTTPError as exc:
            raise ProviderError(
                f"{self.provider} returned HTTP {exc.status_code}; reservation retained.",
                is_transient=exc.status_code in {408, 429, 500, 502, 503, 504},
                request_audit=request_audit,
            ) from None
        except ModelAPIError:
            raise ProviderError(
                f"{self.provider} transport failure; reservation retained.",
                is_transient=True,
                request_audit=request_audit,
            ) from None
        self.responses.append(response)
        text = "\n".join(part.content for part in response.parts if isinstance(part, TextPart))
        tool_calls = [{"id": part.tool_call_id, "type": "function", "function": {
            "name": part.tool_name, "arguments": part.args_as_json_str(),
        }} for part in response.parts if isinstance(part, ToolCallPart)]
        stop_reason = response.finish_reason or ("tool_calls" if tool_calls else "stop")
        stop_metadata = _stop_metadata(response)
        incoming = response.usage.input_tokens
        outgoing = response.usage.output_tokens
        if type(incoming) is not int or type(outgoing) is not int or min(incoming, outgoing) < 0:
            raise ProviderError(
                f"{self.provider} response included invalid usage; reservation retained.",
                is_transient=False,
                request_audit={
                    **request_audit,
                    "served_model_name": response.model_name or self.name,
                    "provider_response": {
                        "content": text, "tool_calls": tool_calls,
                        "stop_reason": stop_reason, **stop_metadata,
                    },
                },
            )
        cost = (incoming * self.prices[0] + outgoing * self.prices[1]) / 1_000_000
        self.budget.settle(reservation, cost, incoming, outgoing)
        return Reply(text, tool_calls, stop_reason, incoming, outgoing,
                     response.model_name or self.name, cost, **stop_metadata)
