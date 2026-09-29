"""One explicit loop; each demo owns its task, tools, responder, and grading."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Protocol

from .budget import BudgetExceeded
from .errors import ProviderError, SampleAttemptError, SampleInfrastructureError
from .nudgers import NUDGERS_BY_LABEL, NudgerPrompt

QUESTION = re.compile(r"<question>(.*?)</question>", re.DOTALL)


def tool(name, description, properties, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": list(properties) if required is None else required,
                       "additionalProperties": False},
    }}


def call(name, arguments, identifier="call_1"):
    return {"id": identifier, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str = "stop"
    input_tokens: int = 0
    output_tokens: int = 0
    served_model_name: str = "scripted"
    cost_usd: float = 0.0
    provider_stop_reason: str | None = None
    stop_details: dict[str, str] = field(default_factory=dict)


class Model(Protocol):
    def complete(self, system: str, tools: list[dict], messages: list[dict]) -> Reply: ...


class DemoSession(Protocol):
    demo: str
    system: str
    request: str
    tools: list[dict]
    is_session_complete: bool

    def execute(self, name: str, arguments: dict): ...
    def answer(self, question: str) -> str: ...
    def grade(self) -> dict: ...


def execute_sample(model: Model, session: DemoSession, *, nudger: str | NudgerPrompt = "none",
                   max_calls=40, max_nudges=3, max_answers=6,
                   should_raise_infrastructure_errors=False):
    """A valid question is never a nudge trigger. Same-response tools still run."""
    nudger_prompt = NUDGERS_BY_LABEL[nudger] if isinstance(nudger, str) else nudger
    messages = [{"role": "user", "content": session.request}]
    question_records, stall_records, usage_records = [], [], []
    num_nudges = 0
    outcome = "call_limit"
    error = None

    def build_attempt_audit(*, attempt_outcome, attempt_error=None, failed_request=None):
        grade = session.grade()
        num_question_continuations = sum(
            bool(question["text_after_question"]) or question["has_tool_calls_in_question_response"]
            for question in question_records
        )
        failed_request_cost = (
            failed_request["estimated_cost_usd"] if failed_request is not None else 0.0
        )
        return {
            "outcome": attempt_outcome,
            "did_sample_pass": (
                attempt_outcome == "completed"
                and grade["is_task_result_correct"]
                and not num_question_continuations
            ),
            "grade": grade, "questions": question_records,
            "question_continuations": num_question_continuations,
            "stalls": stall_records, "nudges": num_nudges,
            "model_calls": len(usage_records) + int(failed_request is not None),
            "usage": usage_records, "failed_request": failed_request,
            "cost_usd": (
                sum(record["cost_usd"] for record in usage_records) + failed_request_cost
            ),
            "messages": messages, "error": attempt_error,
        }

    for _ in range(max_calls):
        try:
            reply = model.complete(session.system, session.tools, messages)
        except (ProviderError, BudgetExceeded) as exc:
            if should_raise_infrastructure_errors:
                failed_request = exc.request_audit if isinstance(exc, ProviderError) else None
                audit = build_attempt_audit(
                    attempt_outcome="infrastructure_error",
                    attempt_error=str(exc),
                    failed_request=failed_request,
                )
                raise SampleAttemptError(exc, audit) from exc
            # Provider exceptions expose a safe, redacted message. The evaluation
            # layer decides whether a transient failure warrants a retry.
            outcome = "budget_limit" if type(exc).__name__ == "BudgetExceeded" else "provider_error"
            error = str(exc)
            break
        except Exception as exc:
            if should_raise_infrastructure_errors:
                error = SampleInfrastructureError(type(exc).__name__)
                audit = build_attempt_audit(
                    attempt_outcome="infrastructure_error",
                    attempt_error=str(error),
                )
                raise SampleAttemptError(error, audit) from exc
            outcome = "provider_error"
            error = type(exc).__name__
            break
        usage_records.append({"model": reply.served_model_name, "input_tokens": reply.input_tokens,
                      "output_tokens": reply.output_tokens, "cost_usd": reply.cost_usd,
                      "stop": reply.stop_reason})
        message = {
            "role": "assistant", "content": reply.text,
            "stop_reason": reply.stop_reason,
            "provider_stop_reason": reply.provider_stop_reason,
            "stop_details": reply.stop_details,
        }
        if reply.tool_calls:
            message["tool_calls"] = reply.tool_calls
        messages.append(message)
        index = len(messages) - 1
        if reply.stop_reason not in {"stop", "tool_call", "tool_calls", "end_turn", "tool_use"}:
            outcome = "truncated" if reply.stop_reason in {"length", "max_tokens"} else "provider_stop"
            break
        matches = list(QUESTION.finditer(reply.text))
        question = "\n".join(m.group(1).strip() for m in matches if m.group(1).strip())
        for item in reply.tool_calls:
            try:
                arguments = json.loads(item["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
                result = session.execute(item["function"]["name"], arguments)
            except (KeyError, ValueError, TypeError) as exc:
                result = {"error": str(exc)}
            messages.append({"role": "tool", "tool_call_id": item["id"],
                             "name": item["function"]["name"],
                             "content": json.dumps(result, ensure_ascii=False)})
        if question:
            question_records.append({"message_index": index, "text": question,
                              "has_tool_calls_in_question_response": bool(reply.tool_calls),
                              "text_after_question": reply.text[matches[-1].end():].strip(),
                              "was_question_answered": False})
        if session.is_session_complete:
            outcome = "completed"
            break
        if question:
            if sum(q["was_question_answered"] for q in question_records) >= max_answers:
                outcome = "answer_limit"
                break
            answer = session.answer(question)
            messages.append({"role": "user", "content": answer})
            question_records[-1]["was_question_answered"] = True
            continue
        if reply.tool_calls:
            continue
        stall_records.append({"message_index": index, "text": reply.text, "after_nudges": num_nudges})
        if nudger_prompt.prompt is None or num_nudges >= max_nudges:
            outcome = "stalled"
            break
        messages.append({"role": "user", "content": nudger_prompt.prompt})
        num_nudges += 1
    return build_attempt_audit(attempt_outcome=outcome, attempt_error=error)
