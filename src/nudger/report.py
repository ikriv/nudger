"""SQL summaries for experiment batches and individual runs."""
from __future__ import annotations

import math
import sqlite3
from typing import Any

from .nudgers import NUDGERS_BY_ID


def wilson(num_successes: int, num_samples: int) -> tuple[float, float]:
    if num_samples == 0:
        return 0.0, 0.0
    z = 1.96
    proportion = num_successes / num_samples
    denominator = 1 + z * z / num_samples
    center = (proportion + z * z / (2 * num_samples)) / denominator
    half_width = z * math.sqrt(
        proportion * (1 - proportion) / num_samples
        + z * z / (4 * num_samples * num_samples)
    ) / denominator
    return max(0.0, center - half_width), min(1.0, center + half_width)


def share(num_matching: int, num_samples: int) -> str:
    return (
        f"{num_matching / num_samples:.0%} ({num_matching}/{num_samples})"
        if num_samples else "-"
    )


def pass_rate(num_passed: int, num_samples: int) -> str:
    if not num_samples:
        return "-"
    low, high = wilson(num_passed, num_samples)
    return f"{share(num_passed, num_samples)} [{low:.0%}-{high:.0%}]"


def latest_batch(db: sqlite3.Connection) -> str | None:
    row = db.execute(
        "SELECT batch_id FROM batches ORDER BY started_at_utc DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def nudger_name(label: str, nudger_id: str) -> str:
    if current := NUDGERS_BY_ID.get(nudger_id):
        label = current.label
    return label if label == nudger_id else f"{label}@{nudger_id[:6]}"


def summarize(
    db: sqlite3.Connection,
    batch_id: str | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    if (batch_id is None) == (run_id is None):
        raise ValueError("Select exactly one batch or run.")
    selection_column = "runs.batch_id" if batch_id is not None else "runs.run_id"
    selection_value = batch_id if batch_id is not None else run_id
    rows = db.execute(
           f"""SELECT
               runs.run_id,
               runs.scenario_id,
               runs.model_kind,
               runs.requested_model_name,
               runs.demo,
               runs.demo_variant,
               runs.question_prompt_variant,
               nudgers.label,
               runs.nudger_id,
               runs.num_samples_scheduled,
               runs.max_model_calls,
               runs.max_output_tokens,
               runs.max_nudges,
               runs.max_answers,
               runs.concurrency,
               runs.max_retries,
               runs.retry_wait_multiplier_seconds,
               runs.retry_wait_max_seconds,
               runs.request_timeout_seconds,
               runs.reasoning_effort,
               runs.input_usd_per_million_tokens,
               runs.output_usd_per_million_tokens,
               runs.model_implementation_sha256,
               runs.software_versions_json,
               COUNT(samples.sample_id),
               COUNT(CASE WHEN samples.sample_status = 'evaluated' THEN 1 END),
               COALESCE(SUM(CASE WHEN samples.sample_status = 'evaluated'
                                 THEN samples.did_sample_pass ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN samples.sample_status = 'evaluated'
                                      AND samples.outcome = 'stalled' THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN samples.sample_status = 'evaluated'
                                      AND samples.num_stalls > 0 THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN samples.sample_status = 'evaluated'
                                      AND samples.num_questions > 0 THEN 1 ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN samples.sample_status = 'evaluated'
                                      AND samples.num_question_continuations > 0
                                 THEN 1 ELSE 0 END), 0),
               AVG(CASE WHEN samples.sample_status = 'evaluated' THEN samples.num_nudges END),
               AVG(CASE WHEN samples.sample_status = 'evaluated' THEN samples.num_model_calls END),
               SUM(samples.estimated_cost_usd),
               COALESCE(SUM(CASE WHEN samples.sample_status = 'infrastructure_error'
                                 THEN 1 ELSE 0 END), 0)
           FROM runs
           JOIN nudgers USING (nudger_id)
           LEFT JOIN samples USING (run_id)
           WHERE {selection_column} = ?
           GROUP BY runs.run_id
           ORDER BY runs.run_id""",
        (selection_value,),
    )
    summaries = []
    for row in rows:
        (
            stored_run_id, scenario_id, model_kind, model, demo, demo_variant,
            question_prompt_variant, label, nudger_id, num_scheduled,
            max_model_calls, max_output_tokens, max_nudges, max_answers,
            concurrency, max_retries, retry_wait_multiplier_seconds,
            retry_wait_max_seconds, request_timeout_seconds, reasoning_effort,
            input_price, output_price, model_implementation_sha256,
            software_versions_json,
            num_recorded, num_evaluated, num_passed, num_ended_stalled,
            num_encountered_stall, num_with_questions,
            num_with_question_continuations, avg_num_nudges,
            avg_num_model_calls, estimated_cost_usd, num_infrastructure_errors,
        ) = row
        summaries.append({
            "run_id": stored_run_id,
            "is_run_complete": num_recorded == num_scheduled,
            "scenario_id": scenario_id,
            "model_kind": model_kind,
            "model": model,
            "demo": demo,
            "demo_variant": demo_variant,
            "question_prompt_variant": question_prompt_variant,
            "nudger": nudger_name(label, nudger_id),
            "num_samples_scheduled": num_scheduled,
            "num_samples_recorded": num_recorded,
            "num_samples_evaluated": num_evaluated,
            "num_passed": num_passed,
            "num_ended_stalled": num_ended_stalled,
            "num_encountered_stall": num_encountered_stall,
            "num_with_questions": num_with_questions,
            "num_with_question_continuations": num_with_question_continuations,
            "avg_num_nudges": avg_num_nudges,
            "avg_num_model_calls": avg_num_model_calls,
            "estimated_cost_usd": estimated_cost_usd,
            "num_infrastructure_errors": num_infrastructure_errors,
            "model_implementation_sha256": model_implementation_sha256,
            "software_versions_json": software_versions_json,
            "settings": (
                f"calls={max_model_calls}, output={max_output_tokens}, "
                f"nudges={max_nudges}, answers={max_answers}, concurrency={concurrency}, "
                f"retries={max_retries}, retry-wait={retry_wait_multiplier_seconds:g}/"
                f"{retry_wait_max_seconds:g}s, timeout={request_timeout_seconds:g}s, "
                f"reasoning={reasoning_effort}, prices={input_price}/{output_price}, "
                f"adapter={model_implementation_sha256[:8]}"
            ),
        })
    return summaries


def print_summary(
    db: sqlite3.Connection,
    *,
    batch_id: str | None = None,
    run_id: str | None = None,
) -> None:
    selection = f"Batch {batch_id}" if batch_id is not None else f"Run {run_id}"
    print(
        f"\n{selection}. Infrastructure-error samples are shown separately "
        "and are not graded."
    )
    print("The pass rate includes a 95% Wilson interval.\n")
    headers = [
        "run", "completeness", "scenario", "model kind", "model", "demo variant", "question prompt variant",
        "nudger", "settings", "pass rate", "ended stalled", "encountered stall",
        "asked", "continued after question", "nudges/sample", "calls/sample",
        "recorded/scheduled", "evaluated", "infrastructure errors", "cost",
    ]
    print("| " + " | ".join(headers) + " |")
    print("|" + "---|" * len(headers))
    for row in summarize(db, batch_id=batch_id, run_id=run_id):
        num_samples = row["num_samples_evaluated"]
        cost = row["estimated_cost_usd"]
        completeness = "complete" if row["is_run_complete"] else "INCOMPLETE"
        cells = [
            row["run_id"], completeness, row["scenario_id"], row["model_kind"], row["model"],
            row["demo_variant"], row["question_prompt_variant"], row["nudger"],
            row["settings"], pass_rate(row["num_passed"], num_samples),
            share(row["num_ended_stalled"], num_samples),
            share(row["num_encountered_stall"], num_samples),
            share(row["num_with_questions"], num_samples),
            share(row["num_with_question_continuations"], num_samples),
            f"{row['avg_num_nudges']:.1f}" if num_samples else "-",
            f"{row['avg_num_model_calls']:.1f}" if num_samples else "-",
            f"{row['num_samples_recorded']}/{row['num_samples_scheduled']}",
            str(num_samples), str(row["num_infrastructure_errors"]),
            f"${cost:.4f}" if cost is not None else "$0.0000",
        ]
        print("| " + " | ".join(cells) + " |")
