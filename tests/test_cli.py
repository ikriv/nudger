import json
import sqlite3

import pytest

from nudger.cli import main, parser


def test_combined_batch_stores_both_demos_in_sqlite(tmp_path):
    database = tmp_path / "results.sqlite"
    transcripts = tmp_path / "transcripts"
    assert main([
        "run", "--scripted", "--nudger", "all", "--no-progress",
        "--db", str(database), "--out", str(transcripts),
    ]) == 0

    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 6
        assert db.execute("SELECT COUNT(*) FROM nudgers").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 6
        assert db.execute(
            "SELECT COUNT(*) FROM runs WHERE num_samples_scheduled = 1"
        ).fetchone()[0] == 6
        assert db.execute(
            "SELECT COUNT(*) FROM runs WHERE length(scenario_id) > 0 "
            "AND length(model_implementation_sha256) = 64"
        ).fetchone()[0] == 6
        assert set(db.execute("SELECT DISTINCT demo FROM runs").fetchall()) == {
            ("refund",), ("columns",),
        }
        assert db.execute("SELECT DISTINCT reasoning_effort FROM runs").fetchall() == [
            ("disabled",),
        ]
        sample = json.loads(db.execute("SELECT sample_json FROM samples LIMIT 1").fetchone()[0])
        assert not {
            "model_kind", "requested_model_name", "settings", "scenario",
            "system_prompt", "tools",
        } & sample.keys()
    transcript_files = list(transcripts.glob("*.md"))
    assert len(transcript_files) == 6
    for transcript_file in transcript_files:
        transcript = transcript_file.read_text(encoding="utf-8")
        assert "SCRIPTED MECHANICS DEMO — no live model API was called" in transcript
        assert "- Model kind: `scripted`" in transcript
        assert "- Requested model: `scripted`" in transcript
        assert "- Reasoning effort: `disabled`" in transcript
        assert "- Limits: model calls" in transcript
        assert "LIVE API SAMPLE" not in transcript
    assert main(["report", str(database)]) == 0


@pytest.mark.parametrize(
    "flag,value",
    [("--samples", "0"), ("--concurrency", "0"), ("--max-calls", "-1"),
     ("--max-nudges", "-1"),
     ("--budget-usd", "nan")],
)
def test_invalid_limits_are_rejected(flag, value):
    with pytest.raises(SystemExit):
        parser().parse_args(["run", "--scripted", flag, value])


def test_live_mode_requires_explicit_model():
    with pytest.raises(SystemExit):
        parser().parse_args(["run"])


def test_question_prompt_variants_are_available_to_both_demos():
    for command in ["refund", "columns", "run"]:
        args = parser().parse_args([
            command, "--scripted", "--question-prompt", "control",
        ])
        assert args.question_prompt == "control"


def test_multiple_models_and_nudgers_can_be_selected():
    args = parser().parse_args([
        "run", "--model", "openai:gpt-5-mini", "--model", "anthropic:claude-haiku-4-5",
        "--nudger", "none", "--nudger", "advanced",
    ])
    assert args.models == ["openai:gpt-5-mini", "anthropic:claude-haiku-4-5"]
    assert args.nudger == ["none", "advanced"]


@pytest.mark.parametrize("model_kind,model,selected,expected", [
    ("scripted", "scripted", "high", "disabled"),
    ("live_api", "openai:gpt-5-mini", "high", "high"),
    ("live_api", "openai:gpt-5-mini", "omit", "omitted"),
    ("live_api", "anthropic:claude-sonnet-4-6", "high", "disabled"),
    ("live_api", "nvidia:test", "high", "omitted"),
    ("live_api", "litellm:test", "high", "omitted"),
    ("live_api", "litellm:gpt-5-mini", "medium", "medium"),
    ("live_api", "litellm:gpt-5-mini", "omit", "omitted"),
    ("live_api", "anthropic:claude-fable-5-1", "medium", "omitted"),
    ("live_api", "litellm:gpt-5.6-sol", "medium", "medium"),
])
def test_effective_reasoning_setting(model_kind, model, selected, expected):
    from nudger.cli import effective_reasoning_effort

    assert effective_reasoning_effort(model_kind, model, selected) == expected


def test_model_adapter_source_is_content_addressed():
    from nudger.cli import model_implementation_sha256

    live_hash = model_implementation_sha256("live_api")
    scripted_hash = model_implementation_sha256("scripted")
    assert len(live_hash) == len(scripted_hash) == 64
    assert live_hash != scripted_hash


def test_budgeted_run_with_unknown_price_directs_user_to_catalog(tmp_path, capsys):
    status = main([
        "refund", "--model", "openai:unlisted-model", "--db", str(tmp_path / "results.sqlite"),
    ])
    assert status == 2
    error = capsys.readouterr().err
    assert "openai:unlisted-model" in error
    assert "model_prices.toml" in error


def test_report_rejects_missing_database(tmp_path, capsys):
    assert main(["report", str(tmp_path / "missing.sqlite")]) == 2
    assert "No database" in capsys.readouterr().err


def test_default_database_appends_batches_and_reports_prior_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["refund", "--scripted", "--nudger", "none", "--no-progress"]) == 0
    database = tmp_path / "experiments" / "results.sqlite"
    with sqlite3.connect(database) as db:
        original = db.execute("SELECT * FROM samples").fetchone()
        first_run = db.execute("SELECT run_id FROM runs").fetchone()[0]

    assert main(["columns", "--scripted", "--nudger", "advanced", "--no-progress"]) == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 2
        assert db.execute("SELECT * FROM samples WHERE run_id=?", (first_run,)).fetchone() == original
    assert main(["report"]) == 0
    assert main(["report", "--run", first_run]) == 0
