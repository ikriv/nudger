import asyncio
from dataclasses import replace

import pytest

from nudger import evaluation
from nudger.errors import ProviderError, SampleAttemptError
from nudger.nudgers import NUDGERS_BY_LABEL


def run_once(monkeypatch, execute_one_sample):
    monkeypatch.setattr(evaluation, "execute_one_sample", execute_one_sample)
    scenario = evaluation.Scenario(
        demo_variant="refund_flirt",
        question_prompt_variant="control",
        nudger=NUDGERS_BY_LABEL["none"],
        max_model_calls=10,
        max_output_tokens=100,
        max_nudges=3,
        max_answers=6,
        concurrency=1,
        max_retries=5,
        retry_wait_multiplier_seconds=0,
        retry_wait_max_seconds=0,
        request_timeout_seconds=120,
    )
    return asyncio.run(evaluation.evaluate_run(
        scenario,
        "scripted",
        None,
        model_kind="scripted",
        num_samples=1,
        reasoning_effort="omit",
        progress=False,
    ))


def test_scenario_identity_covers_limits_prompts_nudger_and_demo_versions():
    base = evaluation.Scenario(
        demo_variant="columns_random", question_prompt_variant="crafted-plus",
        nudger=NUDGERS_BY_LABEL["advanced"], max_model_calls=10,
        max_output_tokens=100, max_nudges=3, max_answers=6, concurrency=1, max_retries=5,
        retry_wait_multiplier_seconds=0, retry_wait_max_seconds=0,
        request_timeout_seconds=120,
    )
    changed_scenarios = [
        replace(base, demo_variant="columns_artists"),
        replace(base, question_prompt_variant="control"),
        replace(base, nudger=NUDGERS_BY_LABEL["none"]),
        replace(base, max_model_calls=11),
        replace(base, max_output_tokens=101),
        replace(base, max_nudges=4),
        replace(base, max_answers=7),
        replace(base, concurrency=2),
        replace(base, max_retries=6),
        replace(base, retry_wait_multiplier_seconds=1),
        replace(base, retry_wait_max_seconds=1),
        replace(base, request_timeout_seconds=121),
    ]
    assert all(base.id != changed.id for changed in changed_scenarios)
    assert base.as_dict()["question_prompt"]
    assert base.as_dict()["nudger_prompt"]
    assert base.as_dict()["system_prompt"]
    assert base.as_dict()["initial_request"]
    assert base.as_dict()["tools"]
    assert base.as_dict()["fixture_version"] == 1
    assert base.as_dict()["responder_version"] == 2
    assert base.as_dict()["fixture_data"]
    assert base.as_dict()["hidden_responder_data"]
    assert len(base.as_dict()["implementation_sha256"]) == 64
    assert base.as_dict()["concurrency"] == 1
    assert base.as_dict()["retry_policy"]["max_retries"] == 5
    assert base.as_dict()["request_timeout_seconds"] == 120


def test_scenario_identity_covers_hidden_responder_data(monkeypatch):
    scenario = evaluation.Scenario(
        demo_variant="columns_random", question_prompt_variant="control",
        nudger=NUDGERS_BY_LABEL["none"], max_model_calls=10,
        max_output_tokens=100, max_nudges=3, max_answers=6, concurrency=1,
        max_retries=5, retry_wait_multiplier_seconds=0,
        retry_wait_max_seconds=0, request_timeout_seconds=120,
    )
    original_id = scenario.id
    monkeypatch.setitem(
        evaluation.COLUMN_DESCRIPTIONS,
        5,
        "The fifth column is a changed hidden fact.",
    )
    assert scenario.id != original_id


def test_transient_failure_retries_the_same_sample(monkeypatch):
    attempts = 0

    def execute_one_sample(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ProviderError("temporary", is_transient=True)
        return {"did_sample_pass": True}

    report = run_once(monkeypatch, execute_one_sample)
    assert attempts == 2
    assert len(report.cases) == 1
    assert report.cases[0].output["sample_status"] == "evaluated"
    assert report.cases[0].output["num_retries"] == 1
    assert not report.failures


def test_non_transient_failure_is_an_infrastructure_error_sample(monkeypatch):
    attempts = 0

    def execute_one_sample(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise ProviderError("permanent", is_transient=False)

    report = run_once(monkeypatch, execute_one_sample)
    assert attempts == 1
    assert len(report.cases) == 1
    assert report.cases[0].output["sample_status"] == "infrastructure_error"
    assert report.cases[0].output["num_retries"] == 0
    assert len(report.cases[0].output["attempts"]) == 1
    assert not report.failures


def test_retry_preserves_prior_attempt_usage_cost_and_transcript(monkeypatch):
    attempts = 0

    def execute_one_sample(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = ProviderError("temporary", is_transient=True)
            raise SampleAttemptError(error, {
                "outcome": "infrastructure_error",
                "usage": [{
                    "model": "served", "input_tokens": 10, "output_tokens": 2,
                    "cost_usd": 0.03, "stop": "stop",
                }],
                "model_calls": 2,
                "cost_usd": 0.07,
                "messages": [{"role": "user", "content": "first attempt"}],
                "error": "temporary",
            })
        return {
            "did_sample_pass": True,
            "usage": [{
                "model": "served", "input_tokens": 5, "output_tokens": 1,
                "cost_usd": 0.02, "stop": "stop",
            }],
            "model_calls": 1,
            "cost_usd": 0.02,
            "messages": [{"role": "user", "content": "second attempt"}],
            "outcome": "completed",
        }

    report = run_once(monkeypatch, execute_one_sample)
    output = report.cases[0].output
    assert output["num_retries"] == 1
    assert output["model_calls"] == 3
    assert output["cost_usd"] == pytest.approx(0.09)
    assert sum(item["input_tokens"] for item in output["usage"]) == 15
    assert [attempt["attempt_number"] for attempt in output["attempts"]] == [1, 2]
    assert output["attempts"][0]["messages"][0]["content"] == "first attempt"
