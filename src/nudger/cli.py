"""Run and report two demos in agent persistence and clarification."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import itertools
import math
from pathlib import Path
import sqlite3
import sys
import uuid

from .budget import Budget, BudgetExceeded
from .db import DEFAULT_DB, Store, json_text
from .demos.columns import COLUMN_VARIANTS
from .demos.refund import REFUND_VARIANTS
from .evaluation import (
    DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_RETRY_WAIT_MAX_SECONDS, DEFAULT_RETRY_WAIT_MULTIPLIER_SECONDS,
    Scenario, evaluate_run, store_samples,
)
from .nudgers import NUDGERS, NUDGERS_BY_LABEL, NudgerPrompt
from .prompts import QUESTION_PROMPT_VARIANTS
from .providers import model_prices
from .report import latest_batch, print_summary

DEMO_VARIANTS = {**REFUND_VARIANTS, **COLUMN_VARIANTS}
DEFAULT_DEMO_VARIANTS = ["refund_flirt", "columns_random"]


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer.")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a positive finite number.")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("Must be a nonnegative integer.")
    return number


def nonnegative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("Must be a nonnegative finite number.")
    return number


def selected_values(selection: str, available_values: dict[str, object]) -> list[str]:
    return list(available_values) if selection == "all" else [selection]


def add_model_arguments(command: argparse.ArgumentParser) -> None:
    model_selection = command.add_mutually_exclusive_group(required=True)
    model_selection.add_argument(
        "--model", action="append", dest="models",
        help=("Exact model label from src/nudger/model_prices.toml; supply the option "
              "once for each model"),
    )
    model_selection.add_argument(
        "--scripted", dest="is_scripted", action="store_true",
        help="Use pre-canned responses instead of calling a real model",
    )


def add_execution_arguments(command: argparse.ArgumentParser) -> None:
    add_model_arguments(command)
    command.add_argument(
        "--nudger", action="append", choices=[*NUDGERS_BY_LABEL, "all"],
        help="Nudger selection; supply multiple options to compare them (default: all)",
    )
    command.add_argument(
        "--question-prompt",
        choices=[*QUESTION_PROMPT_VARIANTS, "all"],
        default="crafted-plus",
    )
    command.add_argument("--samples", type=positive_int, default=1)
    command.add_argument("--concurrency", type=positive_int, default=2)
    command.add_argument("--db", type=Path, default=DEFAULT_DB)
    command.add_argument("--out", type=Path, default=Path("results/transcripts"))
    command.add_argument("--max-calls", type=positive_int, default=40)
    command.add_argument("--max-output", type=positive_int, default=8192)
    command.add_argument("--max-nudges", type=nonnegative_int, default=3)
    command.add_argument("--max-answers", type=positive_int, default=6)
    command.add_argument("--max-retries", type=nonnegative_int, default=DEFAULT_MAX_RETRIES)
    command.add_argument(
        "--retry-wait-multiplier", type=nonnegative_float,
        default=DEFAULT_RETRY_WAIT_MULTIPLIER_SECONDS,
    )
    command.add_argument(
        "--retry-wait-max", type=nonnegative_float,
        default=DEFAULT_RETRY_WAIT_MAX_SECONDS,
    )
    command.add_argument(
        "--request-timeout", type=positive_float,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    command.add_argument("--budget-usd", type=positive_float, default=2.0)
    command.add_argument("--reasoning", choices=["omit", "low", "medium", "high"], default="medium")
    command.add_argument("--note", default="")
    command.add_argument("--no-progress", dest="has_progress", action="store_false")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    combined = commands.add_parser("run", help="Run selected demo variants in one batch")
    add_execution_arguments(combined)
    combined.add_argument(
        "--demo-variant", action="append", choices=[*DEMO_VARIANTS, "all"],
        help="Demo variant; defaults to refund_flirt and columns_random",
    )

    refund = commands.add_parser("refund", help="Run the refund demo")
    add_execution_arguments(refund)
    refund.add_argument(
        "--demo-variant", choices=[*REFUND_VARIANTS, "all"], default="refund_flirt"
    )

    columns = commands.add_parser("columns", help="Run the columns demo")
    add_execution_arguments(columns)
    columns.add_argument(
        "--demo-variant", choices=[*COLUMN_VARIANTS, "all"], default="columns_random"
    )

    report = commands.add_parser("report", help="Summarize a stored batch or run")
    report.add_argument("database", type=Path, nargs="?", default=DEFAULT_DB)
    report_selection = report.add_mutually_exclusive_group()
    report_selection.add_argument("--batch", dest="batch_id")
    report_selection.add_argument("--run", dest="run_id")
    return root


def get_demo_variants(args: argparse.Namespace) -> list[str]:
    if args.command == "run":
        selections = args.demo_variant or DEFAULT_DEMO_VARIANTS
        if "all" in selections:
            return list(DEMO_VARIANTS)
        return list(dict.fromkeys(selections))
    if args.command == "refund":
        return selected_values(args.demo_variant, REFUND_VARIANTS)
    return selected_values(args.demo_variant, COLUMN_VARIANTS)


def get_nudgers(args: argparse.Namespace) -> list[NudgerPrompt]:
    selections = args.nudger or ["all"]
    if "all" in selections:
        return list(NUDGERS)
    return [NUDGERS_BY_LABEL[label] for label in dict.fromkeys(selections)]


def get_scenarios(args: argparse.Namespace) -> list[Scenario]:
    demo_variants = get_demo_variants(args)
    question_prompt_variants = selected_values(
        args.question_prompt, QUESTION_PROMPT_VARIANTS
    )
    nudgers = get_nudgers(args)
    return [
        Scenario(
            demo_variant=demo_variant,
            question_prompt_variant=question_prompt_variant,
            nudger=nudger,
            max_model_calls=args.max_calls,
            max_output_tokens=args.max_output,
            max_nudges=args.max_nudges,
            max_answers=args.max_answers,
            concurrency=args.concurrency,
            max_retries=args.max_retries,
            retry_wait_multiplier_seconds=args.retry_wait_multiplier,
            retry_wait_max_seconds=args.retry_wait_max,
            request_timeout_seconds=args.request_timeout,
        )
        for demo_variant, question_prompt_variant, nudger in itertools.product(
            demo_variants, question_prompt_variants, nudgers
        )
    ]


def effective_reasoning_effort(
    model_kind: str, requested_model_name: str, selected_effort: str
) -> str:
    from .providers import ANTHROPIC_DEFAULT_THINKING_MODELS

    if model_kind != "scripted" and requested_model_name.removeprefix("anthropic:") in ANTHROPIC_DEFAULT_THINKING_MODELS:
        return "omitted"
    if model_kind == "scripted" or requested_model_name.startswith("anthropic:"):
        return "disabled"
    if requested_model_name.startswith("litellm:gpt-"):
        return "omitted" if selected_effort == "omit" else selected_effort
    if requested_model_name.startswith(("nvidia:", "litellm:")) or selected_effort == "omit":
        return "omitted"
    return selected_effort


def package_versions() -> dict[str, str]:
    result = {"python": sys.version.split()[0]}
    for package in (
        "nudger", "pydantic", "pydantic-ai", "pydantic-evals",
        "tenacity", "httpx", "openai", "anthropic",
    ):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not-installed"
    return result


def model_implementation_sha256(model_kind: str) -> str:
    """Identify the checked-out adapter code that issued model requests."""
    package_dir = Path(__file__).parent
    source_names = (
        ("cli.py", "providers.py", "budget.py")
        if model_kind == "live_api"
        else ("cli.py", "scripted_model.py")
    )
    digest = hashlib.sha256()
    for source_name in source_names:
        digest.update(source_name.encode())
        digest.update((package_dir / source_name).read_bytes())
    return digest.hexdigest()


def make_identifier() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def report_command(
    database: Path, requested_batch_id: str | None, requested_run_id: str | None
) -> int:
    if not database.exists():
        print(f"No database at {database}.", file=sys.stderr)
        return 2
    with sqlite3.connect(database) as db:
        batch_id = None if requested_run_id else (requested_batch_id or latest_batch(db))
        if batch_id is None and requested_run_id is None:
            print(f"No batches in {database}.", file=sys.stderr)
            return 2
        print_summary(db, batch_id=batch_id, run_id=requested_run_id)
    return 0


def run_command(args: argparse.Namespace) -> int:
    scenarios = get_scenarios(args)
    model_kind = "scripted" if args.is_scripted else "live_api"
    model_names = ["scripted"] if args.is_scripted else args.models
    prices_by_model: dict[str, tuple[float, float] | None] = {
        "scripted": None
    }
    if model_kind == "live_api":
        for model_name in model_names:
            prices_by_model[model_name] = model_prices(model_name)

    batch_id = make_identifier()
    num_runs = len(scenarios) * len(model_names)
    num_samples = num_runs * args.samples
    print(
        f"{model_kind.upper()} BATCH {batch_id}: {num_runs} runs, "
        f"{num_samples} samples."
    )
    if model_kind == "live_api":
        print(f"Cumulative API allowance: ${args.budget_usd:.2f}.")

    with Store(args.db) as store:
        for scenario in scenarios:
            store.add_nudger(scenario.nudger)
        store.add_batch({
            "batch_id": batch_id,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "concurrency": args.concurrency,
            "software_versions_json": json_text(package_versions()),
            "note": args.note,
        })

        budget_scope = (
            nullcontext(None)
            if model_kind == "scripted"
            else Budget(args.db.parent, args.budget_usd)
        )
        with budget_scope as budget:
            for model_name, scenario in itertools.product(model_names, scenarios):
                run_id = make_identifier()
                reasoning_effort = effective_reasoning_effort(
                    model_kind, model_name, args.reasoning
                )
                prices = prices_by_model[model_name]
                run_record = {
                    "run_id": run_id,
                    "batch_id": batch_id,
                    "scenario_id": scenario.id,
                    "model_kind": model_kind,
                    "requested_model_name": model_name,
                    "demo": scenario.demo,
                    "demo_variant": scenario.demo_variant,
                    "question_prompt_variant": scenario.question_prompt_variant,
                    "nudger_id": scenario.nudger.id,
                    "num_samples_scheduled": args.samples,
                    "max_model_calls": scenario.max_model_calls,
                    "max_output_tokens": scenario.max_output_tokens,
                    "max_nudges": scenario.max_nudges,
                    "max_answers": scenario.max_answers,
                    "concurrency": scenario.concurrency,
                    "max_retries": scenario.max_retries,
                    "retry_wait_multiplier_seconds": scenario.retry_wait_multiplier_seconds,
                    "retry_wait_max_seconds": scenario.retry_wait_max_seconds,
                    "request_timeout_seconds": scenario.request_timeout_seconds,
                    "reasoning_effort": reasoning_effort,
                    "model_implementation_sha256": model_implementation_sha256(model_kind),
                    "input_usd_per_million_tokens": prices[0] if prices else None,
                    "output_usd_per_million_tokens": prices[1] if prices else None,
                    "software_versions_json": json_text(package_versions()),
                    "scenario_json": json_text(scenario.as_dict()),
                }
                store.add_run(run_record)
                evaluation_report = asyncio.run(evaluate_run(
                    scenario,
                    model_name,
                    budget,
                    model_kind=model_kind,
                    num_samples=args.samples,
                    reasoning_effort=args.reasoning,
                    progress=args.has_progress,
                ))
                store_samples(
                    store, run_id, evaluation_report, args.out,
                    run_context=run_record,
                )
            if budget is not None:
                print(f"Cumulative estimated/reserved API cost: ${budget.charged():.6f}")
        print_summary(store.db, batch_id=batch_id)
    print(f"Stored batch in {args.db}; Markdown transcripts are in {args.out}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "report":
        return report_command(args.database, args.batch_id, args.run_id)
    try:
        return run_command(args)
    except (ValueError, BudgetExceeded) as exc:
        print(str(exc), file=sys.stderr)
        return 2
