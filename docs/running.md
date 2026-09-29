# Command-line reference

This is one Python package with two demos. The terms *demo*, *scenario*, *run*,
and *sample* are defined in [NOMENCLATURE.md](../NOMENCLATURE.md).

## Installation

Use Python 3.11 or later. From the repository root, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On macOS or Linux, activate with `source .venv/bin/activate` instead.
After installation, `nudger` and `python -m nudger` are equivalent.
The examples use the latter so they run with the selected Python environment.

To check the mechanics without calling a model:

```powershell
python -m nudger run --scripted --db results/scripted.sqlite
python -m nudger report results/scripted.sqlite
```

**Scripted mode uses pre-canned responses instead of calling a real model.**
Its results are labelled `scripted` and are not evidence of model behavior.
The default selection above produces six runs with one sample each.

This implementation uses scripted customer and owner replies in both modes.
It does not have an interactive console where you can supply those replies.

## Credentials and models

Set the environment variable for the provider you want to use. For example,
in PowerShell:

```powershell
$env:OPENAI_API_KEY = 'your-key'
$env:ANTHROPIC_API_KEY = 'your-key'
$env:NVIDIA_API_KEY = 'your-key'
$env:LITELLM_API_KEY = 'your-virtual-key'
$env:LITELLM_BASE_URL = 'https://your-litellm-proxy.example'
```

Set only the key you need. In a POSIX shell, use `export NAME='value'` instead.
The program does not load `.env` files or search for key files.

Choose an exact model label from
[model_prices.toml](../src/nudger/model_prices.toml). The label includes the
provider, for example `openai:gpt-5-mini` or
`anthropic:claude-sonnet-4-6`. NVIDIA endpoints use `nvidia:` followed by
the model name listed in that file.

LiteLLM uses `litellm:` followed by a deployment alias, such as
`litellm:gpt-5-mini`. Set both the virtual key and proxy URL. The aliases and
prices in the catalog must match your proxy's `/model/info` response.

PydanticAI translates the shared messages and tool definitions for each API.
OpenAI uses Chat Completions and defaults to medium reasoning effort.
Anthropic uses Messages. Sonnet 4.6 and the older models use disabled thinking;
Fable 5, Fable 5.1, and Opus 5.5 retain their mandatory default thinking. NVIDIA uses its
OpenAI-compatible endpoint without the OpenAI reasoning setting.
LiteLLM uses its configured OpenAI-compatible proxy; GPT aliases receive the
selected reasoning effort, while other aliases use the proxy's defaults.
The adapters do not set temperature, a stop sequence, or a forced tool choice.

## Commands

| Command | Purpose |
| --- | --- |
| `run` | Run selected demo variants. Defaults to `refund_flirt` and `columns_random`. |
| `refund` | Run only refund variants. Defaults to `refund_flirt`. |
| `columns` | Run only column variants. Defaults to `columns_random`. |
| `report [database]` | Print a text summary of saved results. Defaults to `experiments/results.sqlite`. |

Add `--help` to any command to see its accepted arguments.

Each execution command creates one batch. Within it, every combination of
selected model, demo variant, question prompt, and nudger gets its own run.
`--samples` applies to **each run**, not to the batch as a whole.
Runs execute in sequence; samples within a run may execute concurrently.

### Demo variants

A demo variant is a named setup for a task:

| Value | Setup |
| --- | --- |
| `refund_flirt` | Customer deflects the first relevant question, then supplies requested facts. |
| `refund_damaged` | Customer gives the reference and says the kettle arrived broken. |
| `refund_missing` | Customer initially omits the reference and reason, then answers questions. |
| `refund_small` | Low-value purchase, eligible for a refund without a return. |
| `refund_expired` | Purchase outside the return window. |
| `columns_random` | Unknown column contains Button, Sparrow, Attention, and Fairly. |
| `columns_artists` | Unknown column contains Picasso, Dali, Malevich, and Kent. |

With `run`, repeat `--demo-variant` to select several, or use
`--demo-variant all` for all seven.
With `refund` or `columns`, supply one value, or `all` for that demo.

### Model and scenario selection

These options apply to `run`, `refund`, and `columns`.

| Option | Default | Meaning |
| --- | --- | --- |
| `--model LABEL` | Required unless scripted | Model label from the price catalog. Repeat to select several models. |
| `--scripted` | Off | Use pre-canned responses. Cannot be combined with `--model`. |
| `--demo-variant VALUE` | Depends on command | Select the task setup as described above. |
| `--nudger VALUE` | `all` | `none`, `continue`, `advanced`, or `all`. May be repeated. |
| `--question-prompt VALUE` | `crafted-plus` | `control`, `crafted`, `crafted-plus`, or `all`. |
| `--samples N` | `1` | Independent samples scheduled for each run. |
| `--reasoning VALUE` | `medium` | Reasoning effort for OpenAI and LiteLLM GPT aliases: `omit`, `low`, `medium`, or `high`. Other providers use their documented settings. |

`continue` sends “Please continue.” after an unfinished stop.
`advanced` tells the agent to continue with available facts, or ask and wait
if a necessary fact is missing. `none` ends the sample at that stop.

The control question prompt explains the question tags. Crafted adds a warning
against assumptions. Crafted-plus also requires the agent to end its response
after asking and wait for the reply. These choices work in both demos.
The exact text is in [prompts.py](../src/nudger/prompts.py) and
[nudgers.py](../src/nudger/nudgers.py).

### Limits, retries, and output

Counts must be positive unless zero is explicitly allowed below.
Timeout and delay values are in seconds.

| Option | Default | Meaning |
| --- | --- | --- |
| `--concurrency N` | `2` | Maximum samples executing concurrently within a run. |
| `--max-calls N` | `40` | Maximum requests to the model per attempt. A request can return several tool calls. |
| `--max-output N` | `8192` | Maximum output tokens requested for one model response. |
| `--max-nudges N` | `3` | Maximum nudge messages per attempt. Zero is allowed. |
| `--max-answers N` | `6` | Maximum scripted replies per attempt. A deflection also counts as a reply. |
| `--max-retries N` | `5` | Additional attempts after transient infrastructure failures. Zero is allowed. |
| `--retry-wait-multiplier SECONDS` | `2` | Multiplier for random exponential delay between retries. Zero is allowed. |
| `--retry-wait-max SECONDS` | `60` | Maximum delay between retries. Zero is allowed. |
| `--request-timeout SECONDS` | `120` | Timeout for a request to the model. |
| `--budget-usd AMOUNT` | `2` | Cumulative estimated API allowance for the database directory. |
| `--db PATH` | `experiments/results.sqlite` | SQLite database to create or append to. |
| `--out DIRECTORY` | `results/transcripts` | Directory for readable Markdown transcripts. |
| `--note TEXT` | Empty | Operator note stored on the batch. |
| `--no-progress` | Progress shown | Hide the evaluation progress display. The final report is still printed. |

A retry restarts the sample with fresh task state after a transient API or
transport failure. It does not create a new sample, and it keeps the earlier
attempt's transcript and cost. The provider SDKs do not retry separately.
Wrong answers, natural stalls, invalid responses, and budget limits do not
trigger retries.

Output truncation is recorded as `truncated`, not as a stall. API and transport
failures are recorded as infrastructure errors, not as model behavior.

## Reproducing the published comparisons

These commands make new live API calls. The original five-sample commands
below reproduce the settings of the [September 26 evaluation](../experiments/2026-09-26/README.md).
The 20-sample commands reproduce the [September 27 evaluation](../experiments/2026-09-27/README.md).
New executions can produce different outcomes.

Refunds: one fixed question prompt, three nudgers, five samples each:

```powershell
python -m nudger refund --model openai:gpt-5-mini --demo-variant refund_flirt --question-prompt crafted-plus --nudger all --samples 5 --db results/reproduction.sqlite --out results/reproduction-transcripts --budget-usd 2
```

Columns: three question prompts, no nudger, five samples each:

```powershell
python -m nudger columns --model anthropic:claude-sonnet-4-6 --demo-variant columns_random --question-prompt all --nudger none --samples 5 --db results/reproduction.sqlite --out results/reproduction-transcripts --budget-usd 2
```

Append live evaluations to `experiments/results.sqlite`. This unified database
is the default for execution and reporting. Use an explicit path under `results/`
for disposable scripted demonstrations or reproductions.

To select both demos and multiple models, use `run` and repeat `--model`.
To use another supported provider, choose its label from the price catalog.

### Evaluations with 20 samples per setting

For a new task/model evaluation, start with `--question-prompt control` and
`--nudger none`. If all 20 samples pass, stop there. If they fail, choose follow-ups
that address the failure: Nudger after stalls, stronger question instructions
after unsupported assumptions or question-protocol failures. The commands below
reproduce the saved comparisons, including earlier exploratory runs; they are
not a requirement to run every setting for every model.

These two commands repeat the refund and Sonnet comparisons through LiteLLM
with 20 samples per run. They produce 60 refund samples and 60 column samples.
Both append to the same database, so the $20 allowance applies to their
combined estimated spending, including retries and unresolved requests.

```powershell
python -m nudger refund --model litellm:gpt-5-mini --demo-variant refund_flirt --question-prompt crafted-plus --nudger all --samples 20 --concurrency 5 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:bedrock-claude-sonnet-4-6 --demo-variant columns_random --question-prompt all --nudger none --samples 20 --concurrency 5 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The GPT-5 mini basic-prompt follow-up first tests the simplest setting, then
adds the two Nudgers after the baseline stalls:

```powershell
python -m nudger refund --model litellm:gpt-5-mini --demo-variant refund_flirt --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model litellm:gpt-5-mini --demo-variant refund_flirt --question-prompt control --nudger continue --nudger advanced --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The [follow-up record](../experiments/2026-09-27/basic-refunds/README.md) contains
all 60 new samples with the provider stop diagnostics preserved.

The advanced-model comparison adds 20 column samples each for Opus 5.5,
GPT-5.6 Sol, and Fable 5.1. It uses basic question-format instructions without Nudger.
The command-line value for these instructions is `control`.
Fable uses the direct Anthropic API; set `ANTHROPIC_API_KEY` as well as the
LiteLLM variables before running:

```powershell
python -m nudger columns --model litellm:bedrock-claude-opus-5-5 --model litellm:gpt-5.6-sol --model anthropic:claude-fable-5-1 --demo-variant columns_random --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The detailed record also preserves an earlier execution of this command with
`--question-prompt crafted-plus`. Keep those instruction sets separate when
interpreting the results. For a model that stalls with basic instructions,
use `--question-prompt crafted` for a follow-up with 20 new samples.

To compare Opus API routes after the LiteLLM provider stops, run the same basic
column evaluation directly through Anthropic:

```powershell
python -m nudger columns --model anthropic:claude-opus-5-5 --demo-variant columns_random --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The advanced refund evaluation uses Sonnet 4.6 and GPT-5.6 Sol with basic
instructions and no Nudger, followed by crafted instructions for Sonnet because
it stalled in the basic-prompt evaluation. Sol did not stall and gets no such
follow-up:

```powershell
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --model litellm:gpt-5.6-sol --demo-variant refund_flirt --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --demo-variant refund_flirt --question-prompt crafted --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The expanded refund comparison adds direct Anthropic Opus without Nudger and
Sonnet with both Nudgers. It keeps basic instructions for comparison with the
Sonnet baseline:

```powershell
python -m nudger refund --model anthropic:claude-opus-5-5 --demo-variant refund_flirt --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --demo-variant refund_flirt --question-prompt control --nudger continue --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The column-prompt follow-up fills the missing Sol crafted-prompt comparison
and the GPT-OSS basic/crafted comparisons. Each command schedules 20 samples
without Nudger:

```powershell
python -m nudger columns --model litellm:gpt-5.6-sol --demo-variant columns_random --question-prompt crafted --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model nvidia:openai/gpt-oss-20b --demo-variant columns_random --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model nvidia:openai/gpt-oss-20b --demo-variant columns_random --question-prompt crafted --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The [follow-up record](../experiments/2026-09-27/column-prompts/README.md)
preserves all 60 new samples and their response diagnostics.

The missing task/model comparisons test GPT-5 mini on columns and GPT-OSS
20B on refunds. Each begins with the basic prompt and no Nudger. Follow-ups
test prompts after guessing and Nudgers after stalls:

```powershell
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt crafted --nudger none --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt crafted-plus --nudger none --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt crafted --nudger advanced --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt control --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt control --nudger continue --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt control --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt crafted --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The [follow-up record](../experiments/2026-09-27/missing-pairs/README.md)
preserves all 160 samples. GPT-5 mini's crafted-plus question loops are
reported as reply-limit failures: valid questions do not trigger Nudger.

The completed matrices add exactly the 15 previously untested settings below.
Advanced has the same prompt text and content hash as the former name; current
reports show the current name without rewriting older stored metadata.

```powershell
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --demo-variant refund_flirt --question-prompt crafted --nudger continue --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --demo-variant refund_flirt --question-prompt crafted --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --demo-variant refund_flirt --question-prompt crafted-plus --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --demo-variant refund_flirt --question-prompt crafted-plus --nudger continue --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model litellm:bedrock-claude-sonnet-4-6 --demo-variant refund_flirt --question-prompt crafted-plus --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt control --nudger continue --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt control --nudger advanced --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt crafted --nudger continue --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt crafted-plus --nudger continue --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_random --question-prompt crafted-plus --nudger advanced --samples 20 --concurrency 5 --max-retries 5 --request-timeout 120 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt crafted --nudger continue --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt crafted --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt crafted-plus --nudger none --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt crafted-plus --nudger continue --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger refund --model nvidia:openai/gpt-oss-20b --demo-variant refund_flirt --question-prompt crafted-plus --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The [matrix record](../experiments/2026-09-27/matrix-gaps/README.md) preserves all
300 new samples and the presentation-only outcome classifier. It groups an
unresolved stall after exhausting nudges under No result. API errors and
refusals remain separate, and original grades and terminal outcomes are unchanged.

The final four GPT-OSS Columns settings complete its matrix:

```powershell
python -m nudger columns --model nvidia:openai/gpt-oss-20b --demo-variant columns_random --question-prompt control --nudger continue --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model nvidia:openai/gpt-oss-20b --demo-variant columns_random --question-prompt control --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model nvidia:openai/gpt-oss-20b --demo-variant columns_random --question-prompt crafted --nudger continue --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
python -m nudger columns --model nvidia:openai/gpt-oss-20b --demo-variant columns_random --question-prompt crafted --nudger advanced --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

The [saved record](../experiments/2026-09-27/oss-columns-gaps/README.md) contains all 80 new samples.

Run these commands in sequence. All models share `experiments/results.sqlite`
and the same $20 cumulative allowance. The budget
lock prevents concurrent commands from spending against the same ledger.
Keep the ledger between commands. The allowance may stop a reproduction
early if prices or token usage differ from the published runs.

### Evaluating a smaller open-source model on columns

Sonnet did not stall in the published column evaluation, so those samples
cannot show whether a Nudger helps after a stall. To evaluate that behavior
with a smaller model, use GPT-OSS 20B through the existing NVIDIA adapter.
Its [NVIDIA endpoint](https://build.nvidia.com/openai/gpt-oss-20b) was available
at zero listed cost when checked on September 27, 2026.

Set `NVIDIA_API_KEY`, then run:

```powershell
python -m nudger columns --model nvidia:openai/gpt-oss-20b --demo-variant columns_random --question-prompt crafted-plus --nudger all --samples 20 --concurrency 5 --max-retries 1 --request-timeout 300 --db experiments/results.sqlite --out results/transcripts --budget-usd 20
```

This schedules three runs and 60 independent samples: 20 for each Nudger
setting, with crafted-plus instructions throughout. It keeps the task, tools,
and scoring unchanged. The longer timeout and single retry were chosen after
an interrupted trial on the slow NVIDIA endpoint. Smaller size is a reason to
try the model, not evidence that it stalls.

```powershell
python -m nudger report experiments/results.sqlite
```

Report both successful samples and samples that encountered a stall, including
stalls followed by recovery. Keep every transcript, including guesses,
failures, and samples with no stalls. Infrastructure errors and truncated
responses do not count as stalls. The [evaluation record](../experiments/2026-09-27/README.md)
contains the results and every saved transcript.

## Reading saved results

Reporting is local: it requires no API key and makes no model requests.

```powershell
python -m nudger report
```

Without a selector, `report` shows the **latest batch**, not every batch.
Use `--batch ID` or `--run ID` to select one; these options are mutually exclusive.

The September 26 database contains two batches. To print both earlier comparisons:

```powershell
python -m nudger report experiments/2026-09-26/results.sqlite --batch 20260926T232513Z-a282ab3d
python -m nudger report experiments/2026-09-26/results.sqlite --batch 20260926T232749Z-b70fdb3c
```

For the new batches, use the report commands in the
[September 27 evaluation record](../experiments/2026-09-27/README.md#reproducing-the-evaluations).

The report prints one row per run, including:

- Recorded versus scheduled samples, so an interrupted run is visible.
- Passed samples and a 95% Wilson interval for the pass rate.
- Samples that ended stalled, separately from samples that encountered a stall
  and later continued.
- Questions, continuations after questions, nudges, model requests, and cost.
- Infrastructure-error counts, excluded from behavioral-rate denominators.

SQLite stores the complete scenario, actual prompts, tools, task data, and
scripted responder data on each run. Each sample stores its result, grade,
transcript, usage, and attempts. Markdown transcripts are readable copies of
those conversations. API keys and hidden model reasoning are not recorded.

See the [database schema](results-schema-proposal.md) and
[scoring method](method.md) for details.
Older databases from before the nomenclature change are not migrated in place;
the program detects that schema and refuses to append to it.

## Prices and budget

[model_prices.toml](../src/nudger/model_prices.toml) is the price catalog. It
records input and output prices, units, the date checked, and provider source
links. If a selected model is missing, the program tells you to add its prices
before running. Check the provider's current rates when adding a model.

The catalog includes NVIDIA prototype endpoints at zero estimated cost.
Service-side request and token limits still apply.

The budget applies cumulatively across live commands and models whose
databases share a directory. Changing the database filename in that directory
does not reset it. An exclusive lock prevents overlapping live processes from
using the same ledger.

Before a request, the program reserves an input allowance based on the UTF-8
request size plus framing, and the full output allowance. After a successful
response, it replaces that reservation with the reported token usage multiplied
by the catalog prices. Cache discounts are ignored. A request with an unknown
outcome retains its reservation; a retry needs another reservation.

These are local estimates, not an account billing limit. The program stops
before its next reservation would exceed the allowance, but incorrect prices
or unexpected token overhead can make the estimate wrong.

The ledger is `usage.jsonl` beside the database, normally `experiments/usage.jsonl`.
The consolidation preserved both current ledgers, including unresolved requests.
Keep this file when clearing a local
database: clearing results must not erase accounted spend. If a process is
killed and leaves `.budget.lock`, verify it has stopped before removing just
that lock file.

## Code and offline checks

The [runner](../src/nudger/runner.py) handles the conversation and nudges.
[Refunds](../src/nudger/demos/refund.py) and
[columns](../src/nudger/demos/columns.py) define the tasks, local tools, scripted
replies, and grading. [Providers](../src/nudger/providers.py) uses PydanticAI's
model API; [evaluation](../src/nudger/evaluation.py) uses Pydantic Evals to
schedule samples. Storage and reporting are separate modules in the same package.

Run the offline checks with:

```powershell
python -m pytest -q
```
