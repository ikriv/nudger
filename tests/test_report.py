import pytest

from nudger.db import Store, json_text
from nudger.nudgers import NUDGERS_BY_LABEL, NudgerPrompt
from nudger.report import pass_rate, print_summary, summarize


def test_schema_represents_batches_runs_and_samples(tmp_path):
    with Store(tmp_path / "results.sqlite") as store:
        tables = {
            row[0] for row in store.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        run_columns = {
            row[1] for row in store.db.execute("PRAGMA table_info(runs)")
        }
        sample_columns = {
            row[1] for row in store.db.execute("PRAGMA table_info(samples)")
        }
    assert {"batches", "runs", "samples", "nudgers"} <= tables
    assert {
        "model_kind", "demo", "demo_variant", "num_samples_scheduled",
        "scenario_id", "question_prompt_variant",
    } <= run_columns
    assert {"sample_number", "sample_status", "num_retries"} <= sample_columns


def add_batch_and_run(store, nudger_id, *, num_samples=2, batch_id="batch-1"):
    if batch_id is not None:
        store.add_batch({
            "batch_id": batch_id,
            "started_at_utc": "2026-09-26T20:00:00+00:00",
            "concurrency": 1,
            "software_versions_json": json_text({}),
            "note": "",
        })
    store.add_run({
        "run_id": "run-1",
        "batch_id": batch_id,
        "scenario_id": "refund_flirt:0123456789abcdef",
        "model_kind": "live_api",
        "requested_model_name": "model",
        "demo": "refund",
        "demo_variant": "refund_flirt",
        "question_prompt_variant": "control",
        "nudger_id": nudger_id,
        "num_samples_scheduled": num_samples,
        "max_model_calls": 10,
        "max_output_tokens": 1000,
        "max_nudges": 3,
        "max_answers": 6,
        "concurrency": 1,
        "max_retries": 5,
        "retry_wait_multiplier_seconds": 2.0,
        "retry_wait_max_seconds": 60.0,
        "request_timeout_seconds": 120.0,
        "reasoning_effort": "medium",
        "model_implementation_sha256": "a" * 64,
        "input_usd_per_million_tokens": 1.0,
        "output_usd_per_million_tokens": 2.0,
        "software_versions_json": json_text({"nudger": "0.1.0"}),
        "scenario_json": json_text({}),
    })


def evaluated_sample(sample_number=1, *, outcome="completed", num_stalls=1):
    return {
        "run_id": "run-1", "sample_number": sample_number, "sample_status": "evaluated",
        "served_model_name": "served", "outcome": outcome, "num_retries": 0,
        "error_message": None, "did_sample_pass": int(outcome == "completed"),
        "is_task_result_correct": int(outcome == "completed"),
        "num_model_calls": 3, "num_stalls": num_stalls, "num_nudges": 1, "num_questions": 1,
        "num_answers": 1, "num_question_continuations": 0, "num_input_tokens": 10,
        "num_output_tokens": 5, "estimated_cost_usd": 0.01, "duration_seconds": 1.0,
        "grade_json": "{}", "transcript_json": "[]", "sample_json": "{}",
        "attempts_json": "[]",
    }


def infrastructure_error_sample(sample_number=2):
    return {
        "run_id": "run-1", "sample_number": sample_number,
        "sample_status": "infrastructure_error", "num_retries": 5,
        "error_message": "timeout", "duration_seconds": 1.0, "sample_json": "{}",
        "num_model_calls": 1, "num_input_tokens": 0, "num_output_tokens": 0,
        "estimated_cost_usd": 0.01, "transcript_json": "[]", "attempts_json": "[]",
    }


def test_report_keeps_infrastructure_errors_out_of_behavioral_denominators(tmp_path):
    with Store(tmp_path / "results.sqlite") as store:
        nudger = NUDGERS_BY_LABEL["continue"]
        store.add_nudger(nudger)
        add_batch_and_run(store, nudger.id)
        store.add_sample(evaluated_sample())
        store.add_sample(infrastructure_error_sample())
        rows = summarize(store.db, "batch-1")
    assert rows[0]["num_samples_evaluated"] == 1
    assert rows[0]["num_passed"] == 1
    assert rows[0]["num_infrastructure_errors"] == 1
    assert rows[0]["estimated_cost_usd"] == 0.02


def test_report_includes_run_where_every_sample_has_an_infrastructure_error(tmp_path):
    with Store(tmp_path / "results.sqlite") as store:
        nudger = NUDGERS_BY_LABEL["none"]
        store.add_nudger(nudger)
        add_batch_and_run(store, nudger.id, num_samples=1)
        store.add_sample(infrastructure_error_sample(1))
        rows = summarize(store.db, "batch-1")
    assert rows[0]["num_samples_evaluated"] == 0
    assert rows[0]["num_infrastructure_errors"] == 1
    assert rows[0]["estimated_cost_usd"] == 0.01


def test_report_distinguishes_ending_stalled_from_encountering_a_stall(tmp_path):
    with Store(tmp_path / "results.sqlite") as store:
        nudger = NUDGERS_BY_LABEL["continue"]
        store.add_nudger(nudger)
        add_batch_and_run(store, nudger.id)
        store.add_sample(evaluated_sample(1, outcome="completed", num_stalls=1))
        store.add_sample(evaluated_sample(2, outcome="stalled", num_stalls=1))
        row = summarize(store.db, "batch-1")[0]
    assert row["num_ended_stalled"] == 1
    assert row["num_encountered_stall"] == 2


def test_partial_run_is_derived_from_recorded_and_scheduled_counts(tmp_path, capsys):
    with Store(tmp_path / "results.sqlite") as store:
        nudger = NUDGERS_BY_LABEL["none"]
        store.add_nudger(nudger)
        add_batch_and_run(store, nudger.id, num_samples=5)
        store.add_sample(evaluated_sample(1))
        store.add_sample(infrastructure_error_sample(2))
        row = summarize(store.db, batch_id="batch-1")[0]
        print_summary(store.db, batch_id="batch-1")
    assert row["is_run_complete"] is False
    assert row["num_samples_scheduled"] == 5
    assert row["num_samples_recorded"] == 2
    assert row["num_samples_evaluated"] == 1
    assert row["num_infrastructure_errors"] == 1
    output = capsys.readouterr().out
    assert "INCOMPLETE" in output
    assert "2/5" in output


def test_run_can_exist_without_a_batch(tmp_path):
    with Store(tmp_path / "results.sqlite") as store:
        nudger = NUDGERS_BY_LABEL["none"]
        store.add_nudger(nudger)
        add_batch_and_run(store, nudger.id, num_samples=1, batch_id=None)
        store.add_sample(evaluated_sample())
        row = summarize(store.db, run_id="run-1")[0]
    assert row["is_run_complete"] is True
    assert row["num_samples_recorded"] == row["num_samples_scheduled"] == 1


def test_store_rejects_sample_number_above_scheduled_count(tmp_path):
    with Store(tmp_path / "results.sqlite") as store:
        nudger = NUDGERS_BY_LABEL["none"]
        store.add_nudger(nudger)
        add_batch_and_run(store, nudger.id, num_samples=1)
        with pytest.raises(ValueError, match="exceeds"):
            store.add_sample(evaluated_sample(2))


def test_pass_rate_shows_counts_and_interval():
    assert pass_rate(1, 2).startswith("50% (1/2) [")
    assert pass_rate(0, 0) == "-"


def test_renamed_prompt_reports_current_label_without_rewriting_saved_metadata(tmp_path):
    advanced = NUDGERS_BY_LABEL["advanced"]
    previous = NudgerPrompt("previous-label", advanced.description, advanced.prompt)
    with Store(tmp_path / "results.sqlite") as store:
        store.add_nudger(previous)
        store.add_nudger(advanced)
        add_batch_and_run(store, advanced.id)
        store.add_sample(evaluated_sample())
        row = summarize(store.db, batch_id="batch-1")[0]
        assert row["nudger"] == f"advanced@{advanced.id[:6]}"
        assert store.db.execute("SELECT label FROM nudgers").fetchone()[0] == "previous-label"
