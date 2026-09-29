"""Render an evaluated sample as a readable Markdown transcript."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def response_lines(message):
    lines = ["```text", message.get("content") or "", "```", ""]
    for item in message.get("tool_calls", []):
        lines += ["```json", json.dumps(item, indent=2), "```", ""]
    if message.get("stop_reason") is not None:
        lines += [f"Normalized stop reason: `{message['stop_reason']}`", ""]
    if message.get("provider_stop_reason") is not None:
        lines += [f"Provider stop reason: `{message['provider_stop_reason']}`", ""]
    if message.get("stop_details"):
        lines += ["Provider stop details:", "", "```json",
                  json.dumps(message["stop_details"], ensure_ascii=False, indent=2), "```", ""]
    return lines


def save_transcript(
    result: dict[str, Any],
    scenario: dict[str, Any],
    run_context: Mapping[str, Any],
    directory: str | Path,
    stem: str,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / stem
    is_scripted = run_context["model_kind"] == "scripted"
    evidence_label = (
        "**SCRIPTED MECHANICS DEMO — no live model API was called.**"
        if is_scripted else
        "**LIVE API SAMPLE — a provider model was called.**"
    )
    input_price = run_context["input_usd_per_million_tokens"]
    output_price = run_context["output_usd_per_million_tokens"]
    prices = (
        "disabled"
        if input_price is None and output_price is None
        else f"input ${input_price}/million; output ${output_price}/million"
    )
    lines = [
        "# Sample transcript", "", f"> {evidence_label}", "",
        "## Provenance", "",
        f"- Run ID: `{run_context['run_id']}`",
        f"- Model kind: `{run_context['model_kind']}`",
        f"- Requested model: `{run_context['requested_model_name']}`",
        f"- Reasoning effort: `{run_context['reasoning_effort']}`",
        f"- Model adapter source: `{run_context['model_implementation_sha256']}`",
        f"- Scheduled samples in run: `{run_context['num_samples_scheduled']}`",
        f"- Limits: model calls `{run_context['max_model_calls']}`, output tokens "
        f"`{run_context['max_output_tokens']}`, nudges `{run_context['max_nudges']}`, "
        f"answers `{run_context['max_answers']}`",
        f"- Evaluation: concurrency `{run_context['concurrency']}`, retries "
        f"`{run_context['max_retries']}`, retry wait multiplier/max "
        f"`{run_context['retry_wait_multiplier_seconds']}`/"
        f"`{run_context['retry_wait_max_seconds']}` seconds, request timeout "
        f"`{run_context['request_timeout_seconds']}` seconds",
        f"- Recorded token prices: {prices}", "",
        f"Outcome: **{result.get('outcome', 'infrastructure_error')}**.", "",
        f"Scenario: `{json.dumps(scenario)}`. Nudger: `{scenario['nudger_label']}`.", "",
        "## System", "", "```text", scenario["system_prompt"], "```", "",
    ]
    for attempt in result["attempts"]:
        lines += [f"## Attempt {attempt['attempt_number']}", "",
                  f"Outcome: **{attempt.get('outcome', 'infrastructure_error')}**. Estimated cost: "
                  f"**${attempt['cost_usd']:.6f}**.", ""]
        if attempt.get("error"):
            lines += [f"Error: `{attempt['error']}`", ""]
        for index, message in enumerate(attempt["messages"]):
            lines += [f"### {index}: {message['role']}", ""]
            if message.get("tool_call_id"):
                lines += [f"Tool-call ID: `{message['tool_call_id']}`", ""]
            lines += response_lines(message)
        failed_response = (attempt.get("failed_request") or {}).get("provider_response")
        if failed_response:
            lines += ["### Response from the failed request", ""]
            lines += response_lines(failed_response)
    lines += ["## Evaluation", "", "```json", json.dumps(result["grade"], indent=2), "```", ""]
    target.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return target.with_suffix(".md")
