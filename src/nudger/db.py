"""SQLite persistence for batches, runs, samples, and nudger prompts."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .nudgers import NudgerPrompt

DEFAULT_DB = Path("experiments") / "results.sqlite"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nudgers (
    nudger_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    prompt TEXT
);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    concurrency INTEGER NOT NULL CHECK (concurrency > 0),
    software_versions_json TEXT NOT NULL,
    note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    batch_id TEXT REFERENCES batches(batch_id),
    scenario_id TEXT NOT NULL,
    model_kind TEXT NOT NULL CHECK (model_kind IN ('live_api', 'scripted')),
    requested_model_name TEXT NOT NULL,
    demo TEXT NOT NULL CHECK (demo IN ('refund', 'columns')),
    demo_variant TEXT NOT NULL CHECK (demo_variant IN (
        'refund_flirt', 'refund_damaged', 'refund_missing', 'refund_small',
        'refund_expired', 'columns_random', 'columns_artists'
    )),
    question_prompt_variant TEXT NOT NULL,
    nudger_id TEXT NOT NULL REFERENCES nudgers(nudger_id),
    num_samples_scheduled INTEGER NOT NULL CHECK (num_samples_scheduled > 0),
    max_model_calls INTEGER NOT NULL CHECK (max_model_calls > 0),
    max_output_tokens INTEGER NOT NULL CHECK (max_output_tokens > 0),
    max_nudges INTEGER NOT NULL CHECK (max_nudges >= 0),
    max_answers INTEGER NOT NULL CHECK (max_answers > 0),
    concurrency INTEGER NOT NULL CHECK (concurrency > 0),
    max_retries INTEGER NOT NULL CHECK (max_retries >= 0),
    retry_wait_multiplier_seconds REAL NOT NULL CHECK (retry_wait_multiplier_seconds >= 0),
    retry_wait_max_seconds REAL NOT NULL CHECK (retry_wait_max_seconds >= 0),
    request_timeout_seconds REAL NOT NULL CHECK (request_timeout_seconds > 0),
    reasoning_effort TEXT NOT NULL,
    model_implementation_sha256 TEXT NOT NULL,
    input_usd_per_million_tokens REAL CHECK (input_usd_per_million_tokens >= 0),
    output_usd_per_million_tokens REAL CHECK (output_usd_per_million_tokens >= 0),
    software_versions_json TEXT NOT NULL,
    scenario_json TEXT NOT NULL,
    CHECK (
        (demo = 'refund' AND demo_variant LIKE 'refund_%')
        OR (demo = 'columns' AND demo_variant LIKE 'columns_%')
    ),
    CHECK (
        (model_kind = 'scripted' AND input_usd_per_million_tokens IS NULL
            AND output_usd_per_million_tokens IS NULL)
        OR (model_kind = 'live_api' AND input_usd_per_million_tokens IS NOT NULL
            AND output_usd_per_million_tokens IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS samples (
    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    sample_number INTEGER NOT NULL CHECK (sample_number > 0),
    sample_status TEXT NOT NULL CHECK (sample_status IN ('evaluated', 'infrastructure_error')),
    served_model_name TEXT,
    outcome TEXT,
    num_retries INTEGER NOT NULL CHECK (num_retries >= 0),
    error_message TEXT,
    did_sample_pass INTEGER CHECK (did_sample_pass IN (0, 1)),
    is_task_result_correct INTEGER CHECK (is_task_result_correct IN (0, 1)),
    num_model_calls INTEGER CHECK (num_model_calls >= 0),
    num_stalls INTEGER CHECK (num_stalls >= 0),
    num_nudges INTEGER CHECK (num_nudges >= 0),
    num_questions INTEGER CHECK (num_questions >= 0),
    num_answers INTEGER CHECK (num_answers >= 0),
    num_question_continuations INTEGER CHECK (num_question_continuations >= 0),
    num_input_tokens INTEGER CHECK (num_input_tokens >= 0),
    num_output_tokens INTEGER CHECK (num_output_tokens >= 0),
    estimated_cost_usd REAL CHECK (estimated_cost_usd >= 0),
    duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
    grade_json TEXT,
    transcript_json TEXT,
    attempts_json TEXT NOT NULL,
    sample_json TEXT NOT NULL,
    UNIQUE (run_id, sample_number),
    CHECK (
        (sample_status = 'evaluated' AND error_message IS NULL AND outcome IS NOT NULL
            AND did_sample_pass IS NOT NULL AND is_task_result_correct IS NOT NULL
            AND num_model_calls IS NOT NULL AND num_stalls IS NOT NULL
            AND num_nudges IS NOT NULL AND num_questions IS NOT NULL
            AND num_answers IS NOT NULL AND num_question_continuations IS NOT NULL
            AND num_input_tokens IS NOT NULL AND num_output_tokens IS NOT NULL
            AND estimated_cost_usd IS NOT NULL
            AND grade_json IS NOT NULL AND transcript_json IS NOT NULL)
        OR
        (sample_status = 'infrastructure_error' AND error_message IS NOT NULL
            AND outcome IS NULL AND did_sample_pass IS NULL AND is_task_result_correct IS NULL
            AND num_model_calls IS NOT NULL AND num_stalls IS NULL AND num_nudges IS NULL
            AND num_questions IS NULL AND num_answers IS NULL
            AND num_question_continuations IS NULL AND num_input_tokens IS NOT NULL
            AND num_output_tokens IS NOT NULL AND estimated_cost_usd IS NOT NULL
            AND transcript_json IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS runs_by_batch ON runs(batch_id);
CREATE INDEX IF NOT EXISTS samples_by_run_and_status ON samples(run_id, sample_status);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        existing_tables = {
            row[0] for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        existing_run_columns = (
            {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}
            if "runs" in existing_tables else set()
        )
        if existing_tables and (
            "batches" not in existing_tables
            or "num_samples_scheduled" not in existing_run_columns
        ):
            self.db.close()
            raise ValueError(
                f"{self.path} uses the retired database schema; move or delete it before running."
            )
        self.db.executescript(SCHEMA)

    def add(self, table: str, row: dict[str, Any]) -> int:
        if table not in {"batches", "runs", "samples"}:
            raise ValueError(f"Unsupported table: {table}")
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        cursor = self.db.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )
        self.db.commit()
        return cursor.lastrowid

    def add_nudger(self, nudger: NudgerPrompt) -> None:
        self.db.execute(
            """INSERT OR IGNORE INTO nudgers
               (nudger_id, label, description, prompt) VALUES (?, ?, ?, ?)""",
            (nudger.id, nudger.label, nudger.description, nudger.prompt),
        )
        self.db.commit()

    def add_batch(self, row: dict[str, Any]) -> None:
        self.add("batches", row)

    def add_run(self, row: dict[str, Any]) -> None:
        self.add("runs", row)

    def add_sample(self, row: dict[str, Any]) -> int:
        scheduled = self.db.execute(
            "SELECT num_samples_scheduled FROM runs WHERE run_id = ?",
            (row["run_id"],),
        ).fetchone()
        if scheduled is not None and row["sample_number"] > scheduled[0]:
            raise ValueError(
                f"sample_number {row['sample_number']} exceeds the run's "
                f"{scheduled[0]} scheduled samples."
            )
        return self.add("samples", row)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
