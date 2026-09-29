# Nudger: helping agents reach the goal without stalling or making things up

An agent should keep working toward the user's goal when it has enough information to take the next step. When a necessary fact is missing, it should ask and wait for the answer. We evaluate how a Nudger and the agent's initial instructions help different models do this.

## The problem

An agent can stop with work left to do. It might ask “Would you like me to continue?” when it already has what it needs. Or it might ask a necessary question in a format the application does not forward to the user. Either way, progress stops.

When directed not to stop under any circumstances, an agent may use invented answers if it can't find the actual facts. I personally observed agents fill database with synthetic data when they could not connect to the real data source. This technically gets the mission accomplished, but the result of that victory is not very useful.

A **Nudger** is a combination of the initial prompt that encourages progress, but discourages unsubstantiated guesses, and a nudging message that is sent to the agent when it stops anyway for no good reason.

## What's in the Code

The repository contains implementation of the nudger with different variants of the initial prompt and the nudging message, and the evaluator that runs those against different models. See below for operating instructions.

## Evaluating the Nudger

The effectiveness of the Nudger depends on multiple factors. 

| Factor          | Variants                                                     |
| --------------- | ------------------------------------------------------------ |
| Initial prompt  | **Basic**: just explains how to ask structured questions<br />**Crafted:** explains how to ask questions and discourages guessing<br />**Crafted Plus**: discourages guessing in even stronger terms |
| Nudging message | **None:** no nudger; just let the agent stall<br />**Please Continue:** sends "Please continue" to the agent went it stalls. No additional instructions.<br />**Advanced:** reminds the agent about the rules and the questions protocol |
| Model           | OpenAI GPT-5 mini<br />OpenAI GPT-OSS 20B<br />Anthropic Sonnet 4.6<br />Anthropic Opus 5.5<br />OpenAI GPT 5.6 Sol<br />Anthropic Fable 5.1 |
| Tasks           | Issuing refunds<br />Naming database columns                 |

The exact nature of "issuing refunds" and "renaming columns" is described in the sections below.

### Results at a Glance

For refunds:

| Model       | Game Changer                                                 |
| ----------- | ------------------------------------------------------------ |
| GPT-5 Mini  | Advanced nudger                                              |
| GPT-OSS 20B | Was not great with any combination; initial prompt improved the quality |
| Sonnet 4.6  | Basic nudger                                                 |
| Opus 5.5    | None; Worked with basic prompt; did not need a nudger        |
| GPT 5.6 Sol | None; Worked with basic prompt; did not need a nudger        |

For column naming:

| Model       | Game Changer                                                 |
| ----------- | ------------------------------------------------------------ |
| GPT-5 Mini  | Initial prompt; Crafted worked better than Crafted Plus      |
| GPT-OSS 20B | Was not great with any combination; both initial prompt and advanced nugder improved the quality |
| Sonnet 4.6  | Initial prompt; Sonnet did not need the nudger, but tended to invent the answers with weaker prompts |
| Opus 5.5    | Blocked most requests citing security                        |
| GPT 5.6 Sol | Initial prompt; did not need the nudger                      |
| Fable 5.1   | Blocked ALL requests citing security                         |

## Refunds and Columns

We considered two tasks: issuing refunds and coming up with descriptive names for columns in a database table.

### Refunds

The agent works at a fictional returns desk. It's job is to obtain from the user the purchase order number and the reason for refund, and determine whether the order is eligible for refund and who pays the shipping. In real life, deterministic aspects of the decision like comparing dates would better be decided by a script, but for simplicity we leave all decisions with the agent.

There are 5 variants of this scenario, depending on the customer's behavior:

- **Flirting customer:** dodges the first question, then provides the requested details about a broken kettle. The agent must ask again and arrange a return with store-paid shipping.
- **Damaged item:** the customer supplies the kettle's order reference and says it arrived broken. The agent can look up the purchase and arrange the return.
- **Missing details:** the customer initially gives no order reference or reason. Questions reveal a change of mind about the kettle; return shipping is the customer's responsibility.
- **Small purchase:** a $12 cable pouch qualifies for a full refund without a return.
- **Expired return:** a broken reading light is outside the return window, so the request must be declined.

### Columns

The agent must give descriptive names to five columns in a SQLite table called `incoming`, preserving every row and value. All columns are straightforward except for the mysterious `col5`.

In the first variant it contains random words.

| col1 | col2 | col3 | col4 | col5 |
| --- | --- | --- | --- | --- |
| mira@example.com | Notebook | $8 | 2026-08-04 | Button |
| owen@example.com | Water bottle | $24 | 2026-08-06 | Sparrow |
| ines@example.com | Desk mat | $19 | 2026-08-09 | Attention |
| noah@example.com | Notebook | $8 | 2026-08-12 | Fairly |

In the second variant `col5` contains artist names.

| col1 | col2 | col3 | col4 | col5 |
| --- | --- | --- | --- | --- |
| mira@example.com | Notebook | $8 | 2026-08-04 | Picasso |
| owen@example.com | Water bottle | $24 | 2026-08-06 | Dali |
| ines@example.com | Desk mat | $19 | 2026-08-09 | Malevich |
| noah@example.com | Notebook | $8 | 2026-08-12 | Kent |

In both cases the LLM is supposed to ask the user what is the meaning of `col5`, since it cannot be reasonably deduced from the data itself. 

Not asking the user and guessing the name is considered a failure.

## Evaluation Process

### The protocol and success criteria

1. The agent is given a prompt explaining the task and how to ask questions. The question must be put inside `<question>...</question>` tags.
2. The agent is supposed to retrieve missing information from the user and return the verdict in JSON format.
3. For refunds it's the refund decision (no refund, refund + seller pays shipping, refund + customer pays shipping, refund + no shipping necessary).
4. For columns we expect the agent to call the `run_sql` tool to rename the columns. We execute the SQL against a real in-memory database.

For refunds, the success is if the agent made the correct refund decision.

For columns the success is that no columns are still named col1...col5, that col5 is now warehouse_name, and that no data was lost or altered.

Other outcomes besides **success** could include:

* **Stall**. The model stopped without asking a question or finishing the task.
* **No result**. The model never arrived to the decision after 40 LLM responses, 6 questions or 3 nudges, whichever comes first.
* **Wrong result**. The model arrived to a wrong conclusion.
* **Inventing the answer.** The model didn't ask expected questions and/or ignored user's data and came up with an answer of its own.

### Running the evaluation

We ran 20 samples of all Nudger type + prompt type + model type + task combinations, except for Opus and Fable. 

For columns, Fable rejected the task for security reasons, and Opus did the same for most attempts.

For refunds, Opus attained a perfect score with basic prompt and no nudger, so we did not attempt more sophisticated settings or more sophisticated and expensive model (Fable).

**NOTE** that to save costs and time we only ran the "flirting" for refunds and the "random" variant for artists. This is not a limitation of the evaluation script, it is purely a data collection decision.

## Results in detail

Each cell describes **20 independent samples**. The percentages in a cell add up to 100%; zero categories are omitted. Prompts run across columns and Nudger choices down rows.

API errors and refusals are separate. Each cell is a new set of samples, so differences between cells can include run-to-run variation. **† means Nudger was configured but never triggered in that run**; its result is not evidence of a Nudger benefit. The detailed record preserves the original grades and terminal outcomes.

### Refunds

#### GPT-5 mini

Advanced worked with the basic prompt. The earlier crafted-plus runs produced the same success rates.

| Nudger / Prompt | Basic | Crafted-plus |
| --- | --- | --- |
| None | **0% succeeded**<br/>100% stalled | **0% succeeded**<br/>100% stalled |
| Please continue | **0% succeeded**<br/>100% wrong result | **0% succeeded**<br/>100% wrong result |
| Advanced | **100% succeeded** | **100% succeeded** |

Without Nudger, questions lacked the required tags. “Please continue” led every sample to decline an eligible return without getting the facts. Advanced rescued every stalled sample with one nudge, after which it asked properly, waited, and recorded the correct decision.

#### GPT-OSS 20B

This model both stalled and made premature refund decisions.

| Nudger / Prompt | Basic                                                        | Crafted                                                  | Crafted-plus                                                 |
| --------------- | ------------------------------------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------ |
| None            | **35% succeeded**<br/>40% stalled<br/>20% wrong result<br/>5% API error | **40% succeeded**<br/>45% stalled<br/>15% wrong result   | **75% succeeded**<br/>15% stalled<br/>5% wrong result<br/>5% API error |
| Please continue | **40% succeeded**<br/>5% no result<br/>50% wrong result<br/>5% API error | **50% succeeded**<br/>35% no result<br/>15% wrong result | **95% succeeded**<br/>5% no result                           |
| Advanced        | **60% succeeded**<br/>10% no result<br/>30% wrong result     | **75% succeeded**<br/>15% no result<br/>10% wrong result | **85% succeeded**<br/>5% wrong result<br/>10% API error      |

The failures include declining before obtaining the customer facts, selecting shipping without the return reason, using the wrong reason code, and exhausting questions or nudges. Advanced rescued 5%, 10%, and 10% with the three prompts. API response errors stay separate from those behaviors.

#### Sonnet

Advanced succeeded with every prompt.

| Nudger / Prompt | Basic | Crafted | Crafted-plus |
| --- | --- | --- | --- |
| None | **0% succeeded**<br/>100% stalled | **20% succeeded**<br/>80% stalled | **10% succeeded**<br/>90% stalled |
| Please continue | **90% succeeded**<br/>5% no result<br/>5% wrong result | **90% succeeded**<br/>5% no result<br/>5% wrong result | **100% succeeded** |
| Advanced | **100% succeeded** | **100% succeeded** | **100% succeeded** |

Advanced rescued 95%, 100%, and 75% of samples with basic, crafted, and crafted-plus instructions, respectively. The remaining successes did not stall. Wrong results include a premature decline and an otherwise-correct result that continued after a question.

#### Opus and GPT-5.6 Sol

Both worked with the basic prompt and no Nudger: **100% success in 20 samples each**. No stronger prompt or Nudger evaluation was needed.

### Columns

#### GPT-5 mini

Crafted instructions improved success. With crafted-plus, the model often got stuck asking permission.

| Nudger / Prompt | Basic | Crafted | Crafted-plus |
| --- | --- | --- | --- |
| None | **35% succeeded**<br/>5% no result<br/>60% invented an answer | **70% succeeded**<br/>10% stalled<br/>5% invented an answer<br/>15% wrong result | **35% succeeded**<br/>65% no result |
| Please continue | **20% succeeded†**<br/>70% invented an answer<br/>10% wrong result | **95% succeeded**<br/>5% invented an answer | **55% succeeded†**<br/>45% no result |
| Advanced | **25% succeeded†**<br/>75% invented an answer | **90% succeeded†**<br/>10% invented an answer | **50% succeeded†**<br/>50% no result |

Invented meanings included `campaign_source` and `promo_code`. Some samples reached the correct final names but kept writing after a question; those count as Wrong result because they violated the protocol.

With crafted instructions and “Please continue,” 90% succeeded without a nudge and 5% were rescued.

With crafted-plus, many samples repeatedly asked permission to inspect or rename the table. The scripted owner explains column meanings but cannot answer permission or naming-preference questions. Properly tagged questions do not trigger Nudger, so these loops end as No result after the reply limit. This limits what the evaluation says about working with a real table owner.

#### GPT-OSS 20B

This smaller open-source model both guessed column meanings and stalled. All nine settings have now been evaluated.

| Nudger / Prompt | Basic                                                        | Crafted                                                      | Crafted-plus                                                 |
| --------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| None            | **15% succeeded**<br/>30% stalled<br/>45% invented an answer<br/>5% wrong result<br/>5% API error | **60% succeeded**<br/>35% stalled<br/>5% no result           | **55% succeeded**<br/>35% stalled<br/>10% wrong result       |
| Please continue | **10% succeeded**<br/>15% no result<br/>55% invented an answer<br/>10% wrong result<br/>10% API error | **35% succeeded**<br/>40% no result<br/>15% invented an answer<br/>10% wrong result | **50% succeeded**<br/>30% no result<br/>20% API error        |
| Advanced        | **20% succeeded**<br/>50% invented an answer<br/>15% wrong result<br/>15% API error | **40% succeeded**<br/>50% no result<br/>5% invented an answer<br/>5% API error | **70% succeeded**<br/>25% no result<br/>5% invented an answer |

Advanced rescued 10%, 5%, and 15% of samples with Basic, Crafted, and Crafted-plus, respectively. The scripted owner sometimes misunderstood reasonable questions, which limits what this comparison says about the model.

#### Sonnet

**Sonnet never stalled on columns.** Its failures were invented meanings for the fifth column, such as `customer_tag` or `promo_code`. No Nudger was used.

| Nudger / Prompt | Basic | Crafted | Crafted-plus |
| --- | --- | --- | --- |
| None | **40% succeeded**<br/>60% invented an answer | **80% succeeded**<br/>20% invented an answer | **100% succeeded** |

#### GPT-5.6 Sol

Crafted instructions were enough for all 20 samples to succeed. Sol never stalled. With the basic prompt it renamed column 5 before receiving the owner's answer; some names invented a business meaning, while others were generic labels. The crafted-plus results came from an earlier evaluation.

| Nudger / Prompt | Basic | Crafted | Crafted-plus |
| --- | --- | --- | --- |
| None | **60% succeeded**<br/>30% invented an answer<br/>10% wrong result | **100% succeeded** | **100% succeeded** |



#### Opus and Fable

- **Opus:** blocked by security filter in most basic-prompt samples.
- **Fable:** blocked by security filter in every sample.

Both returned this refusal text:

> This request triggered restrictions on violative cyber content and was blocked under Anthropic's Usage Policy.

## Command-line reference

Run these commands from the repository root after [installation](docs/running.md#installation).

### Synopsis

```text
python -m nudger run     (--model LABEL [--model LABEL ...] | --scripted) [OPTIONS]
python -m nudger refund  (--model LABEL [--model LABEL ...] | --scripted) [OPTIONS]
python -m nudger columns (--model LABEL [--model LABEL ...] | --scripted) [OPTIONS]
python -m nudger report [DATABASE] [--batch ID | --run ID]
```

`run` selects both demos by default; `refund` and `columns` select only their named demo. Each selected model × demo variant × question prompt × Nudger combination is a separate run. `--samples N` repeats **each run** N times with fresh task state.

### Connection and API key

**Yes, the prefix of `--model` selects the connection.** The program splits the label at the first colon: the prefix selects the client, API-key environment variable, and base URL; the part after the colon is the model name sent to that client. There are no `--url` or `--api-key` flags.

| Label prefix | API-key variable | URL used |
| --- | --- | --- |
| `openai:` | `OPENAI_API_KEY` | OpenAI SDK default; the project does not pass a base URL. |
| `anthropic:` | `ANTHROPIC_API_KEY` | Anthropic SDK default; the project does not pass a base URL. |
| `nvidia:` | `NVIDIA_API_KEY` | Fixed in code: `https://integrate.api.nvidia.com/v1`. |
| `litellm:` | `LITELLM_API_KEY` | Read from `LITELLM_BASE_URL`; set this to your proxy's OpenAI-compatible base URL. |

For example, to use a LiteLLM deployment in Bash:

```bash
LITELLM_API_KEY='your-virtual-key'
LITELLM_BASE_URL='https://your-litellm-proxy.example'
export LITELLM_API_KEY LITELLM_BASE_URL
```

Set only the variables required by the prefix you use. The program does not load `.env` files. A `litellm:` label is a deployment alias; your proxy must expose that name and its prices in `/model/info`.

These exact labels occur in the saved evaluations, including the earlier five-sample runs:

| Model | `--model` label(s) used |
| --- | --- |
| GPT-5 mini | `litellm:gpt-5-mini`, `openai:gpt-5-mini` |
| Claude Sonnet 4.6 | `litellm:bedrock-claude-sonnet-4-6`, `anthropic:claude-sonnet-4-6` |
| Claude Opus 5.5 | `litellm:bedrock-claude-opus-5-5`, `anthropic:claude-opus-5-5` |
| GPT-5.6 Sol | `litellm:gpt-5.6-sol` |
| Claude Fable 5.1 | `anthropic:claude-fable-5-1` |
| GPT-OSS 20B | `nvidia:openai/gpt-oss-20b` |

The full set of configured labels and prices is in [model_prices.toml](src/nudger/model_prices.toml).

### Options for `run`, `refund`, and `columns`

`--model LABEL` and `--scripted` are mutually exclusive; choose one.

| Option | Values; default | Meaning |
| --- | --- | --- |
| `--model LABEL` | Exact entry in `model_prices.toml`; required unless `--scripted` | Select a live model. Repeat to compare several models. |
| `--scripted` | Off by default | Do not call LLM, use pre-canned model responses instead; off by default |
| `--demo-variant VALUE` | See variant table below; `run`: `refund_flirt` and `columns_random`; `refund`: `refund_flirt`; `columns`: `columns_random` | Select the task setup. Repeat for `run` to select several; `refund` and `columns` accept one value or `all`. |
| `--nudger VALUE` | `none`, `continue`, `advanced`, `all`; default `all` | What to do when the agent stops with work unfinished. Repeat to select several. `none` ends the sample; `continue` sends “Please continue”; `advanced` reminds the agent to act or ask and wait. |
| `--question-prompt VALUE` | `control`, `crafted`, `crafted-plus`, `all`; default `crafted-plus` | Initial question instructions. `control` explains question tags; `crafted` also discourages guesses; `crafted-plus` also says to stop and wait after a question. |
| `--samples N` | Positive integer; default `1` | Independent samples per run, not per command. |
| `--reasoning VALUE` | `omit`, `low`, `medium`, `high`; default `medium` | Reasoning effort for direct OpenAI and LiteLLM GPT aliases. Other providers use their own settings. |
| `--concurrency N` | Positive integer; default `2` | Maximum simultaneous samples within a run. |
| `--max-calls N` | Positive integer; default `40` | Maximum model requests per attempt; one response may contain several tool calls. |
| `--max-output N` | Positive integer; default `8192` | Maximum output tokens requested for one model response. |
| `--max-nudges N` | Nonnegative integer; default `3` | Maximum Nudger messages per attempt. |
| `--max-answers N` | Positive integer; default `6` | Maximum scripted customer or owner replies per attempt. |
| `--max-retries N` | Nonnegative integer; default `5` | Additional attempts after transient infrastructure errors. |
| `--retry-wait-multiplier SECONDS` | Nonnegative number; default `2` | Multiplier for exponential retry delay. |
| `--retry-wait-max SECONDS` | Nonnegative number; default `60` | Maximum retry delay. |
| `--request-timeout SECONDS` | Positive number; default `120` | Timeout for one model request. |
| `--budget-usd AMOUNT` | Positive number; default `2` | Cumulative estimated API allowance for the database directory. |
| `--db PATH` | Default `experiments/results.sqlite` | SQLite results database to create or append to. |
| `--out DIRECTORY` | Default `results/transcripts` | Directory for readable transcripts. |
| `--note TEXT` | Default empty | Note stored with the batch. |
| `--no-progress` | Off by default | Hide the progress display; the final report still prints. |
| `--help` | — | Show command-specific usage. |

`run` accepts repeated `--demo-variant` options, while `refund` and `columns` take one. `--demo-variant all` selects every variant allowed for that command. `--nudger all` selects all three Nudger choices; `--question-prompt all` selects all three question prompts.

### Demo variants

| Command | `--demo-variant` | Setup |
| --- | --- | --- |
| `refund` or `run` | `refund_flirt` | Customer deflects the first relevant question, then supplies requested facts. |
| `refund` or `run` | `refund_damaged` | Customer supplies the order reference and says the kettle is broken. |
| `refund` or `run` | `refund_missing` | Customer initially omits the reference and reason, then answers questions. |
| `refund` or `run` | `refund_small` | Low-value purchase eligible for a refund without a return. |
| `refund` or `run` | `refund_expired` | Purchase outside the return window. |
| `columns` or `run` | `columns_random` | Unknown column contains Button, Sparrow, Attention, and Fairly. |
| `columns` or `run` | `columns_artists` | Unknown column contains Picasso, Dali, Malevich, and Kent. |

### `report` options

| Argument or option | Default | Meaning |
| --- | --- | --- |
| `DATABASE` | `experiments/results.sqlite` | Results database to read. |
| `--batch ID` | Latest batch | Summarize a particular batch. Cannot be combined with `--run`. |
| `--run ID` | None | Summarize a particular run. Cannot be combined with `--batch`. |
| `--help` | — | Show report usage. |

### Examples

After setting `LITELLM_API_KEY` and `LITELLM_BASE_URL`, run the flirting-customer and artist-name scenarios without changing the published results database:

```bash
python -m nudger refund --model litellm:gpt-5-mini --demo-variant refund_flirt --question-prompt control --nudger none --samples 20 --db results/my-runs.sqlite

python -m nudger columns --model litellm:gpt-5-mini --demo-variant columns_artists --question-prompt control --nudger none --samples 20 --db results/my-runs.sqlite

python -m nudger report results/my-runs.sqlite
```

See [docs/running.md](docs/running.md) for installation and reproduction commands.
