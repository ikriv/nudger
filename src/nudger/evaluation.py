"""Pydantic Evals execution and persistence for runs and their samples."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from pydantic_evals import Case as EvalInput, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_evals.reporting import EvaluationReport
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential

from .budget import Budget
from .db import Store, json_text
from .demos.columns import (
    BASE, COLUMN_DESCRIPTIONS, COLUMN_VARIANTS,
    FIXTURE_VERSION as COLUMNS_FIXTURE_VERSION,
    RESPONDER_VERSION as COLUMNS_RESPONDER_VERSION, ColumnsSession,
)
from .demos.refund import (
    ORDERS, TODAY, REFUND_VARIANTS, FIXTURE_VERSION as REFUND_FIXTURE_VERSION,
    RESPONDER_VERSION as REFUND_RESPONDER_VERSION, RefundSession,
)
from .errors import ProviderError, SampleAttemptError
from .nudgers import NudgerPrompt
from .providers import APIModel
from .prompts import (
    COLUMNS_REQUEST, COLUMNS_ROLE, QUESTION_PROMPT_VARIANTS, REFUNDS_POLICY,
)
from .recording import save_transcript
from .runner import execute_sample
from .scripted_model import ScriptedModel

SAMPLE_SUFFIX = re.compile(r" \[(\d+)/(\d+)\]$")
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_WAIT_MULTIPLIER_SECONDS = 2.0
DEFAULT_RETRY_WAIT_MAX_SECONDS = 60.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class Scenario:
    """Every model-independent input that can affect one sample."""

    demo_variant: str
    question_prompt_variant: str
    nudger: NudgerPrompt
    max_model_calls: int
    max_output_tokens: int
    max_nudges: int
    max_answers: int
    concurrency: int
    max_retries: int
    retry_wait_multiplier_seconds: float
    retry_wait_max_seconds: float
    request_timeout_seconds: float

    def __post_init__(self) -> None:
        if self.demo_variant not in REFUND_VARIANTS and self.demo_variant not in COLUMN_VARIANTS:
            raise ValueError(f"Unknown demo variant: {self.demo_variant}")

    @property
    def demo(self) -> str:
        return "refund" if self.demo_variant in REFUND_VARIANTS else "columns"

    @property
    def id(self) -> str:
        encoded = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True).encode()
        return f"{self.demo_variant}:{hashlib.sha256(encoded).hexdigest()[:16]}"

    def create_session(self) -> RefundSession | ColumnsSession:
        if self.demo == "refund":
            return RefundSession(self.demo_variant, self.question_prompt_variant)
        return ColumnsSession(self.question_prompt_variant, self.demo_variant)

    def implementation_sha256(self) -> str:
        selected_demo_file = (
            Path(__file__).with_name("demos") / "refund.py"
            if self.demo == "refund"
            else Path(__file__).with_name("demos") / "columns.py"
        )
        implementation_files = [
            Path(__file__), Path(__file__).with_name("runner.py"), selected_demo_file,
        ]
        digest = hashlib.sha256()
        for source_file in implementation_files:
            digest.update(source_file.name.encode())
            digest.update(source_file.read_bytes())
        return digest.hexdigest()

    def as_dict(self) -> dict[str, Any]:
        fixture_version = (
            REFUND_FIXTURE_VERSION if self.demo == "refund" else COLUMNS_FIXTURE_VERSION
        )
        responder_version = (
            REFUND_RESPONDER_VERSION if self.demo == "refund" else COLUMNS_RESPONDER_VERSION
        )
        if self.demo == "refund":
            variant = REFUND_VARIANTS[self.demo_variant]
            initial_request = variant[0]
            system_prompt = REFUNDS_POLICY + "\n" + QUESTION_PROMPT_VARIANTS[self.question_prompt_variant]
            tools = RefundSession.tools
            fixture_data = {
                "today": TODAY.isoformat(), "orders": ORDERS,
                "selected_variant": {
                    "request": variant[0], "reference": variant[1],
                    "reason": variant[2], "are_required_facts_known": variant[3],
                },
            }
            hidden_responder_data = {
                "reference": variant[1], "reason": variant[2],
                "does_customer_initially_know_required_facts": variant[3],
            }
        else:
            initial_request = COLUMNS_REQUEST
            system_prompt = COLUMNS_ROLE + "\n" + QUESTION_PROMPT_VARIANTS[self.question_prompt_variant]
            tools = ColumnsSession.tools
            variant_values = COLUMN_VARIANTS[self.demo_variant]
            fixture_data = {
                "base_rows": BASE,
                "variant_values": variant_values,
                "rows": [row + [variant_values[index % 4]] for index, row in enumerate(BASE)],
            }
            hidden_responder_data = {"column_descriptions": COLUMN_DESCRIPTIONS}
        return {
            "demo": self.demo,
            "demo_variant": self.demo_variant,
            "question_prompt_variant": self.question_prompt_variant,
            "nudger_id": self.nudger.id,
            "nudger_label": self.nudger.label,
            "nudger_prompt": self.nudger.prompt,
            "question_prompt": QUESTION_PROMPT_VARIANTS[self.question_prompt_variant],
            "initial_request": initial_request,
            "system_prompt": system_prompt,
            "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
            "tools": tools,
            "fixture_version": fixture_version,
            "responder_version": responder_version,
            "fixture_data": fixture_data,
            "hidden_responder_data": hidden_responder_data,
            "implementation_sha256": self.implementation_sha256(),
            "max_model_calls": self.max_model_calls,
            "max_output_tokens": self.max_output_tokens,
            "max_nudges": self.max_nudges,
            "max_answers": self.max_answers,
            "concurrency": self.concurrency,
            "retry_policy": {
                "max_retries": self.max_retries,
                "wait_random_exponential_multiplier_seconds": self.retry_wait_multiplier_seconds,
                "wait_random_exponential_max_seconds": self.retry_wait_max_seconds,
            },
            "request_timeout_seconds": self.request_timeout_seconds,
        }


@dataclass
class SampleGrade(Evaluator[Scenario, dict[str, Any], None]):
    def evaluate(self, ctx: EvaluatorContext[Scenario, dict[str, Any], None]) -> dict[str, bool]:
        if ctx.output["sample_status"] != "evaluated":
            return {}
        return {"passed": bool(ctx.output["did_sample_pass"])}


def is_transient_error(error: BaseException) -> bool:
    return (
        isinstance(error, (ProviderError, SampleAttemptError))
        and error.is_transient
    )


def build_dataset(scenario: Scenario) -> Dataset[Scenario, dict[str, Any], None]:
    # Pydantic Evals calls an evaluation input a Case. Keep that library term
    # inside this adapter; the experiment exposed by this project uses samples.
    evaluation_inputs = [EvalInput(name=scenario.id, inputs=scenario)]
    return Dataset(name="nudger", cases=evaluation_inputs, evaluators=[SampleGrade()])


def execute_one_sample(
    scenario: Scenario,
    requested_model_name: str,
    budget: Budget | None,
    *,
    model_kind: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    session = scenario.create_session()
    model: ScriptedModel | APIModel | None = None
    try:
        if model_kind == "scripted":
            model = ScriptedModel(session)
        else:
            model = APIModel(
                requested_model_name,
                budget,
                max_output=scenario.max_output_tokens,
                reasoning=reasoning_effort,
                request_timeout=scenario.request_timeout_seconds,
            )
        result = execute_sample(
            model,
            session,
            nudger=scenario.nudger,
            max_calls=scenario.max_model_calls,
            max_nudges=scenario.max_nudges,
            max_answers=scenario.max_answers,
            should_raise_infrastructure_errors=True,
        )
        return result
    finally:
        if model is not None and hasattr(model, "close"):
            model.close()
        if hasattr(session, "db"):
            session.db.close()


async def evaluate_run(
    scenario: Scenario,
    requested_model_name: str,
    budget: Budget | None,
    *,
    model_kind: str,
    num_samples: int,
    reasoning_effort: str,
    progress: bool,
) -> EvaluationReport[Scenario, dict[str, Any], None]:
    dataset = build_dataset(scenario)

    async def execute_with_retries(sample_scenario: Scenario) -> dict[str, Any]:
        attempt_number = 0
        failed_attempts: list[dict[str, Any]] = []

        def error_audit(error: BaseException, number: int) -> dict[str, Any]:
            if isinstance(error, SampleAttemptError):
                audit = dict(error.attempt_audit)
            elif isinstance(error, ProviderError) and error.request_audit is not None:
                audit = {
                    "usage": [],
                    "model_calls": 1,
                    "cost_usd": error.request_audit["estimated_cost_usd"],
                    "messages": [],
                    "failed_request": error.request_audit,
                    "error": str(error),
                }
            else:
                audit = {
                    "usage": [], "model_calls": 0, "cost_usd": 0.0,
                    "messages": [], "error": str(error) or type(error).__name__,
                }
            audit["attempt_number"] = number
            return audit

        def retain_failed_attempt(retry_state) -> None:
            error = retry_state.outcome.exception()
            failed_attempts.append(error_audit(error, retry_state.attempt_number))

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception(is_transient_error),
                wait=wait_random_exponential(
                    multiplier=sample_scenario.retry_wait_multiplier_seconds,
                    max=sample_scenario.retry_wait_max_seconds,
                ),
                stop=stop_after_attempt(sample_scenario.max_retries + 1),
                reraise=True,
                before_sleep=retain_failed_attempt,
            ):
                with attempt:
                    attempt_number = attempt.retry_state.attempt_number
                    result = await asyncio.to_thread(
                        execute_one_sample,
                        sample_scenario,
                        requested_model_name,
                        budget,
                        model_kind=model_kind,
                        reasoning_effort=reasoning_effort,
                    )
            successful_attempt = dict(result)
            successful_attempt["attempt_number"] = attempt_number
            all_attempts = [*failed_attempts, successful_attempt]
            result["sample_status"] = "evaluated"
            result["num_retries"] = len(all_attempts) - 1
            result["attempts"] = all_attempts
            result["usage"] = [
                usage for audit in all_attempts for usage in audit.get("usage", [])
            ]
            result["model_calls"] = sum(audit.get("model_calls", 0) for audit in all_attempts)
            result["cost_usd"] = sum(audit.get("cost_usd", 0.0) for audit in all_attempts)
            return result
        except Exception as error:
            failed_attempts.append(error_audit(error, attempt_number or 1))
            usage = [item for audit in failed_attempts for item in audit.get("usage", [])]
            last_attempt = failed_attempts[-1] if failed_attempts else {}
            return {
                "sample_status": "infrastructure_error",
                "num_retries": max(0, len(failed_attempts) - 1),
                "error_message": str(error) or type(error).__name__,
                "attempts": failed_attempts,
                "usage": usage,
                "model_calls": sum(
                    audit.get("model_calls", 0) for audit in failed_attempts
                ),
                "cost_usd": sum(audit.get("cost_usd", 0.0) for audit in failed_attempts),
                "messages": last_attempt.get("messages", []),
                "grade": last_attempt.get("grade"),
            }

    return await dataset.evaluate(
        execute_with_retries,
        name=f"{scenario.id} @ {requested_model_name}",
        max_concurrency=scenario.concurrency,
        progress=progress,
        repeat=num_samples,  # Pydantic Evals' parameter name for sample count.
    )


def sample_number(evaluation_name: str) -> int:
    match = SAMPLE_SUFFIX.search(evaluation_name)
    return int(match.group(1)) if match else 1


def store_samples(
    store: Store,
    run_id: str,
    evaluation_report: EvaluationReport[Scenario, dict[str, Any], None],
    transcript_directory: Path,
    run_context: Mapping[str, Any],
) -> None:
    for evaluated_sample in evaluation_report.cases:
        result = evaluated_sample.output
        common = {
            "run_id": run_id,
            "sample_number": sample_number(evaluated_sample.name),
            "sample_status": result["sample_status"],
            "num_retries": result["num_retries"],
            "duration_seconds": evaluated_sample.task_duration,
        }
        if result["sample_status"] == "infrastructure_error":
            usage = result["usage"]
            sample_id = store.add_sample({
                **common,
                "error_message": result["error_message"],
                "served_model_name": usage[-1]["model"] if usage else None,
                "num_model_calls": result["model_calls"],
                "num_input_tokens": sum(item["input_tokens"] for item in usage),
                "num_output_tokens": sum(item["output_tokens"] for item in usage),
                "estimated_cost_usd": result["cost_usd"],
                "grade_json": (
                    json_text(result["grade"]) if result.get("grade") is not None else None
                ),
                "transcript_json": json_text(result["messages"]),
                "attempts_json": json_text(result["attempts"]),
                "sample_json": json_text(result),
            })
            save_transcript(
                result,
                evaluated_sample.inputs.as_dict(),
                run_context,
                transcript_directory,
                f"{run_id}-{sample_id}",
            )
            continue

        usage = result["usage"]
        sample_id = store.add_sample({
            **common,
            "served_model_name": usage[-1]["model"] if usage else None,
            "outcome": result["outcome"],
            "did_sample_pass": result["did_sample_pass"],
            "is_task_result_correct": result["grade"]["is_task_result_correct"],
            "num_model_calls": result["model_calls"],
            "num_stalls": len(result["stalls"]),
            "num_nudges": result["nudges"],
            "num_questions": len(result["questions"]),
            "num_answers": sum(
                question["was_question_answered"] for question in result["questions"]
            ),
            "num_question_continuations": result["question_continuations"],
            "num_input_tokens": sum(item["input_tokens"] for item in usage),
            "num_output_tokens": sum(item["output_tokens"] for item in usage),
            "estimated_cost_usd": result["cost_usd"],
            "grade_json": json_text(result["grade"]),
            "transcript_json": json_text(result["messages"]),
            "attempts_json": json_text(result["attempts"]),
            "sample_json": json_text(result),
        })
        save_transcript(
            result,
            evaluated_sample.inputs.as_dict(),
            run_context,
            transcript_directory,
            f"{run_id}-{sample_id}",
        )

    if evaluation_report.failures:
        raise RuntimeError("Pydantic Evals failed outside the recorded sample boundary.")
