# Results schema

SQLite is the authoritative experiment record. The executable schema is in
[`src/nudger/db.py`](../src/nudger/db.py). It uses four tables:

- `batches` groups the runs started by one CLI invocation and stores invocation
  time, concurrency, software versions, and the operator note. A run may also
  exist without a batch; batches are an optional operational grouping.
- `nudgers` stores each prompt once under a content-derived identifier. The
  no-nudge control keeps the stable identifier `none`.
- `runs` stores one scenario evaluated against one requested model. Its columns
  identify the demo, demo variant, question-prompt variant, nudger, model kind,
  model settings, limits, and scheduled sample count. `scenario_json` preserves
  the complete model-independent input, including the initial request, system
  prompt and hash, tool schemas, nudger text, actual fixture data, hidden responder
  data, execution limits, retry policy, and implementation hash. The run also
  records the source hash for the selected model adapter.
- `samples` stores each execution within a run that reached a terminal result.
  `sample_number` is one-based. `sample_status` is either `evaluated` or `infrastructure_error`, and
  `num_retries` records evaluator retries of that sample. Evaluated samples keep
  their outcome, measurements, grade, visible transcript, usage, duration, and
  complete sample JSON. `attempts_json` retains each attempt's available
  transcript and cost data. Successful attempts retain reported token usage and
  settled cost. Failed provider requests retain the reservation estimate and
  reservation audit details, including the reservation ID, when that audit is
  available.
  The database directory's `usage.jsonl` is the authoritative reservation and
  settlement journal. Infrastructure-error samples keep the same available
  audit and cost data plus their final error; they do not enter behavioral-rate
  denominators.

Reports print one row per run. They show recorded/scheduled samples plus evaluated
and infrastructure-error counts, so interruption cannot masquerade as a smaller
complete run. The scenario ID and full run settings prevent distinct experimental
cells from being silently combined.
