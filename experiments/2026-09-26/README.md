# Experiment results — September 26, 2026

This record contains two live API batches: six runs, each with five independent
samples. All 30 samples are included, including failures. The code used for
these batches is in commit `520638f`.

The [main README](../../README.md) explains the experiment in plain language.
[NOMENCLATURE.md](../../NOMENCLATURE.md) defines the units: one run evaluates
one scenario against one model; a sample is an independent execution within
that run.

## Files

- [results.sqlite](results.sqlite): the full database, copied without modification.
- [All sample transcripts](#all-samples): readable conversations, copied without modification.
- [usage.jsonl](usage.jsonl): the cost ledger for these two batches.
- [SHA256SUMS](SHA256SUMS): hashes of the database, ledger, and transcript files.

The database is the authoritative record. Each run stores its actual prompts,
tools, data, responder settings, execution limits, and source hashes. Samples
store visible messages, tool calls, tool results, grading, and usage.
The Markdown transcripts include the full instructions as well as the conversation.

## What was compared

For refunds, we used `refund_flirt` with the crafted-plus initial question
instructions throughout. The only change between the three scenarios was the
nudger: none, “Please continue”, or balanced.

For columns, we used `columns_random` with no nudger throughout. The only
change between the three scenarios was the initial question prompt: control,
crafted, or crafted-plus.

All samples started fresh. The no-nudge and nudged refund samples are independent
executions, not branches from one saved conversation.
Samples within a run could execute two at a time; the runs executed sequentially.

A question enclosed in `<question>...</question>` reaches a fixed script
representing the customer or owner. Other assistant text goes to the activity
log. The initial instructions explain this routing in every scenario.

A stall is an unfinished text response with neither a tool call nor a valid
tagged question. Asking for information outside the tags therefore counts as
a stall. Asking correctly and waiting for a reply does not.

The application does not automatically cut off a response at a question.
If the model also calls tools in that response, those tools execute before
the user's reply. The grader records that ordering. Output limits, API errors,
and transport errors are not counted as natural stalls.

## Results

“Asked” below means that the model used the question tags. “Encountered a stall”
includes samples that recovered later. “Ended stalled” refers only to the final
outcome. “Passed” requires both the correct task result and the required
clarification behavior.

| Demo | Nudger | Question prompt | Passed | Encountered a stall | Ended stalled | Asked | Estimated cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| refund | none | crafted-plus | 0/5 | 5/5 | 5/5 | 0/5 | $0.00522125 |
| refund | continue | crafted-plus | 0/5 | 5/5 | 0/5 | 0/5 | $0.02083550 |
| refund | balanced | crafted-plus | 5/5 | 5/5 | 0/5 | 5/5 | $0.03279225 |
| columns | none | control | 2/5 | 0/5 | 0/5 | 2/5 | $0.17140800 |
| columns | none | crafted | 4/5 | 0/5 | 0/5 | 4/5 | $0.27198300 |
| columns | none | crafted-plus | 5/5 | 0/5 | 0/5 | 5/5 | $0.28612800 |

There were no infrastructure-error samples, retries, or continuations after a
tagged question in these two batches. All scheduled samples were recorded.
Every column sample reached completion, including the four that used an
unsupported meaning.

### Refund behavior

Without a nudger, all five samples asked for the order details outside the
required tags. Their questions went into the activity log, so the customer
script never received them and the conversations stopped.

With “Please continue”, each sample encountered three stalls and received three
nudges. None used the tags. Each eventually recorded a decline for insufficient
information without receiving the order reference or reason, or looking up the
order. They completed the workflow but failed the task.

With the balanced nudge, each sample first stalled in the same way, then received
one nudge. Each asked two correctly tagged questions: the customer deflected the
first and answered the second. The model then looked up R-210 and recorded the
correct decision: a return of the broken $68 kettle, with the shop paying shipping.

This demonstrates recovery from a missed question protocol. It does not
demonstrate a needless pause by an agent that already had enough information.

Start with [no nudger, sample 1](transcripts/20260926T232513Z-7a2e1c76-1.md),
[“Please continue”, sample 1](transcripts/20260926T232527Z-a34af585-6.md), and
[balanced, sample 1](transcripts/20260926T232615Z-530a1239-11.md).

### Column behavior

With control instructions, three samples renamed the unknown field without
asking. Two called it `customer_tag`; the third called it `customer_alias`.
The other two asked the owner and used `warehouse_name`.

With crafted instructions, four samples asked and waited. One still renamed
the field `promo_code` without asking.

With crafted-plus, all five asked, waited for the owner, and used
`warehouse_name`. None needed a nudge.

These failures involved assigning unsupported meanings and skipping the
question. None of these samples asked a tagged question and then invented
the owner's answer. Earlier exploratory observations of that different failure
are not included in these results.

Start with [control, sample 1](transcripts/20260926T232749Z-e9e5b123-16.md),
[crafted, sample 2](transcripts/20260926T232834Z-c353cd2d-22.md), and
[crafted-plus, sample 2](transcripts/20260926T232944Z-82a93a6f-27.md).

## Task data and scoring

### Refund

The fixed shop date is September 1, 2026. R-210 is a $68 travel kettle bought
on August 25. The customer starts by flirting, without supplying the reference
or return reason. The customer script deflects the first relevant question,
then supplies the facts requested in later questions.

The policy permits refusal after three relevant unanswered questions.
One deflection does not justify refusal. A successful sample must obtain the
facts, look up the purchase, and record `return_required`, 6800 cents,
shop-paid shipping, and reason `return_required`.

The decision tool accepts a structurally valid wrong decision. It does not
reject the answer and steer the model toward the expected result. No money
moves; all orders and decisions are fictional.

### Columns

The export contains eight fixed rows and five columns. The first four contain
customer email addresses, products, prices, and dates. The last cycles through
Button, Sparrow, Attention, and Fairly. Those values label warehouses.

The model's initial context does not contain that meaning. A relevant question
to the owner script supplies it, along with the required name
`warehouse_name`. Both responder scripts use visible keyword matching, not
another model or a human operator.

A successful sample must preserve every row and value, receive the owner's
explanation, rename the fifth column to `warehouse_name` without an earlier
rename, and finish. The other four column meanings are not comprehensively
graded.

The grader counts any rename of the fifth column before the owner's answer as
premature, even a neutral placeholder. In this batch, the four failures assigned
specific unsupported business meanings, as described above.

Passing this grade does not imply that every statement or SQL attempt was
correct. For example, [crafted-plus sample 1](transcripts/20260926T232944Z-82a93a6f-26.md)
made an unrelated incorrect claim about SQLite column renaming and tried a
disallowed statement before recovering. It still asked and waited correctly
and preserved the data. That transcript is retained with the others.

More detail: [scoring method](../../docs/method.md).

## Exact prompts

The task instructions are included in every transcript and in the scenario
saved on each run. The question instructions below are appended to the task's
system prompt. They are available for either demo.

### control

```text
To contact the person responsible for this task, write your question inside <question> and </question>. The application forwards only the text inside those tags. Other assistant text goes into the activity log.
```

### crafted

```text
To contact the person responsible for this task, write your question inside <question> and </question>. The application forwards only the text inside those tags. Other assistant text goes into the activity log.
Distinguish observations from facts supplied by the user or tools. A plausible pattern does not establish a missing fact. Ask for necessary missing facts rather than assuming them.
```

### crafted-plus

```text
To contact the person responsible for this task, write your question inside <question> and </question>. The application forwards only the text inside those tags. Other assistant text goes into the activity log.
Distinguish observations from facts supplied by the user or tools. A plausible pattern does not establish a missing fact. Ask for necessary missing facts rather than assuming them.
The application displays your tagged question to the responsible person. End your response immediately after </question>. Wait for a later user message with their answer before doing more work. Do not write an imagined reply or call tools in the response that asks the question.
```

### Nudges

With `none`, no message is sent after a stall. The sample ends there.

With `continue`, the message is:

```text
Please continue.
```

With `balanced`, the message is:

```text
Review what remains unfinished. If you can do the next part with the tools and information already available, do it. If a necessary fact is missing, request it with <question>...</question> and wait for the reply. A guess is not a reply.
```

The balanced nudge contains no refund policy, order reference, column meaning,
or expected answer. It restates how to proceed or request a missing fact.

## Models and settings

| Setting | Refunds | Columns |
| --- | --- | --- |
| Requested model | `openai:gpt-5-mini` | `anthropic:claude-sonnet-4-6` |
| Served model | `gpt-5-mini-2025-08-07` | `claude-sonnet-4-6` |
| Reasoning | Medium | Thinking disabled |
| Input price recorded, USD per million tokens | 0.25 | 3.00 |
| Output price recorded, USD per million tokens | 2.00 | 15.00 |
| Initial question instructions | Crafted-plus | Control, crafted, crafted-plus |
| Nudgers | None, continue, balanced | None |

All runs used five samples, concurrency two, at most 40 requests to the model
per attempt, at most 8192 output tokens per response, at most three nudges, and
at most six scripted replies. The timeout was 120 seconds per request.
Up to five retries were allowed for transient infrastructure errors, with
random exponential delay using a two-second multiplier and a 60-second cap.
No retry was used.

The adapters did not set temperature, a stop sequence, or a forced tool choice.
Source hashes and exact settings are saved in the database, alongside the
model names.

The recorded environment used Python 3.13.3, Pydantic 2.13.5,
Pydantic Evals 2.45.0, OpenAI SDK 3.19.2, Anthropic SDK 1.8.0,
HTTPX 0.28.1, and Tenacity 9.1.4.

There is a metadata naming error in this version: the saved package list says
`pydantic-ai: not-installed` because it checks that distribution name.
The installed dependency is `pydantic-ai-slim` 2.45.0, also pinned in
[pyproject.toml](../../pyproject.toml). The database has been left unchanged.

### Batches and run identifiers

Refund batch: `20260926T232513Z-a282ab3d`, started at 23:25:13 UTC.
Column batch: `20260926T232749Z-b70fdb3c`, started at 23:27:49 UTC.
Both dates are September 26, 2026.

- **refund, none, crafted-plus**: run `20260926T232513Z-7a2e1c76`; scenario `refund_flirt:bb8bda779cf2bd5c`.
- **refund, continue, crafted-plus**: run `20260926T232527Z-a34af585`; scenario `refund_flirt:06c615e750dceca2`.
- **refund, balanced, crafted-plus**: run `20260926T232615Z-530a1239`; scenario `refund_flirt:83677d255744ffc9`.
- **columns, none, control**: run `20260926T232749Z-e9e5b123`; scenario `columns_random:7aa7ef360e849be2`.
- **columns, none, crafted**: run `20260926T232834Z-c353cd2d`; scenario `columns_random:c81660b592fdaba7`.
- **columns, none, crafted-plus**: run `20260926T232944Z-82a93a6f`; scenario `columns_random:a913bbbd2316695b`.

## Cost and excluded setup work

The estimated cost of the 30 published samples was **$0.788368**:
$0.058849 for refunds and $0.729519 for columns. The ledger contains
154 settled requests and no outstanding reservations. Costs use the recorded
token prices; they are not a provider invoice.

An earlier setup attempt failed because the local adapter reused API clients
across incompatible event-loop lifetimes. That failed setup was discarded
before the corrected code produced these two batches. It is not behavioral
evidence and is not in this database. Its possible API cost is also not
included in the $0.788368 above, which covers only the published batches.

Older exploratory transcripts elsewhere in the repository are not part of
this experiment. All samples from the two batches identified here are included.

## Limits of the result

Five samples per setting are enough to show the observed behavior, not to
estimate a reliable general failure rate. The tasks and models were selected
after earlier exploration. These are demonstrations, not a random survey of
agent behavior.

The comparison uses fixed scripts as the customer and owner, and an explicit
tag format for questions. A chat application that forwards all assistant text
to a human would not have this particular routing failure.

The refund comparison supports a benefit from the balanced nudge in this setup.
The column comparison supports a benefit from clearer initial instructions.
Because no nudger was used for columns, that result cannot be attributed to
a nudger. It also does not establish that the balanced nudge is necessary or
sufficient for other models and tasks.

## Reproducing and reporting

The [command-line reference](../../docs/running.md) includes commands to run
both comparisons again and to print the two saved batch reports without making
API calls. New executions can differ even with the same settings.
Model aliases can also resolve differently later; the served names above
identify what these samples actually used.

## All samples

Each link contains the full visible conversation, including system and user
messages, assistant messages, tool calls, and tool results. “Pass” refers to
the grading rules above, not an absence of all mistakes.

### refund: none, crafted-plus

- [Sample 1 (database ID 1)](transcripts/20260926T232513Z-7a2e1c76-1.md): Fail; stalled; 1 stall; 0 nudges; 0 tagged questions.
- [Sample 2 (database ID 2)](transcripts/20260926T232513Z-7a2e1c76-2.md): Fail; stalled; 1 stall; 0 nudges; 0 tagged questions.
- [Sample 3 (database ID 3)](transcripts/20260926T232513Z-7a2e1c76-3.md): Fail; stalled; 1 stall; 0 nudges; 0 tagged questions.
- [Sample 4 (database ID 4)](transcripts/20260926T232513Z-7a2e1c76-4.md): Fail; stalled; 1 stall; 0 nudges; 0 tagged questions.
- [Sample 5 (database ID 5)](transcripts/20260926T232513Z-7a2e1c76-5.md): Fail; stalled; 1 stall; 0 nudges; 0 tagged questions.

### refund: continue, crafted-plus

- [Sample 1 (database ID 6)](transcripts/20260926T232527Z-a34af585-6.md): Fail; completed; 3 stalls; 3 nudges; 0 tagged questions.
- [Sample 2 (database ID 7)](transcripts/20260926T232527Z-a34af585-7.md): Fail; completed; 3 stalls; 3 nudges; 0 tagged questions.
- [Sample 3 (database ID 8)](transcripts/20260926T232527Z-a34af585-8.md): Fail; completed; 3 stalls; 3 nudges; 0 tagged questions.
- [Sample 4 (database ID 9)](transcripts/20260926T232527Z-a34af585-9.md): Fail; completed; 3 stalls; 3 nudges; 0 tagged questions.
- [Sample 5 (database ID 10)](transcripts/20260926T232527Z-a34af585-10.md): Fail; completed; 3 stalls; 3 nudges; 0 tagged questions.

### refund: balanced, crafted-plus

- [Sample 1 (database ID 11)](transcripts/20260926T232615Z-530a1239-11.md): Pass; completed; 1 stall; 1 nudge; 2 tagged questions.
- [Sample 2 (database ID 12)](transcripts/20260926T232615Z-530a1239-12.md): Pass; completed; 1 stall; 1 nudge; 2 tagged questions.
- [Sample 3 (database ID 13)](transcripts/20260926T232615Z-530a1239-13.md): Pass; completed; 1 stall; 1 nudge; 2 tagged questions.
- [Sample 4 (database ID 14)](transcripts/20260926T232615Z-530a1239-14.md): Pass; completed; 1 stall; 1 nudge; 2 tagged questions.
- [Sample 5 (database ID 15)](transcripts/20260926T232615Z-530a1239-15.md): Pass; completed; 1 stall; 1 nudge; 2 tagged questions.

### columns: none, control

- [Sample 1 (database ID 16)](transcripts/20260926T232749Z-e9e5b123-16.md): Fail; completed; 0 stalls; 0 nudges; 0 tagged questions; fifth column: customer_tag.
- [Sample 2 (database ID 17)](transcripts/20260926T232749Z-e9e5b123-17.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 3 (database ID 18)](transcripts/20260926T232749Z-e9e5b123-18.md): Fail; completed; 0 stalls; 0 nudges; 0 tagged questions; fifth column: customer_tag.
- [Sample 4 (database ID 19)](transcripts/20260926T232749Z-e9e5b123-19.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 5 (database ID 20)](transcripts/20260926T232749Z-e9e5b123-20.md): Fail; completed; 0 stalls; 0 nudges; 0 tagged questions; fifth column: customer_alias.

### columns: none, crafted

- [Sample 1 (database ID 21)](transcripts/20260926T232834Z-c353cd2d-21.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 2 (database ID 22)](transcripts/20260926T232834Z-c353cd2d-22.md): Fail; completed; 0 stalls; 0 nudges; 0 tagged questions; fifth column: promo_code.
- [Sample 3 (database ID 23)](transcripts/20260926T232834Z-c353cd2d-23.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 4 (database ID 24)](transcripts/20260926T232834Z-c353cd2d-24.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 5 (database ID 25)](transcripts/20260926T232834Z-c353cd2d-25.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.

### columns: none, crafted-plus

- [Sample 1 (database ID 26)](transcripts/20260926T232944Z-82a93a6f-26.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 2 (database ID 27)](transcripts/20260926T232944Z-82a93a6f-27.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 3 (database ID 28)](transcripts/20260926T232944Z-82a93a6f-28.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 4 (database ID 29)](transcripts/20260926T232944Z-82a93a6f-29.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
- [Sample 5 (database ID 30)](transcripts/20260926T232944Z-82a93a6f-30.md): Pass; completed; 0 stalls; 0 nudges; 1 tagged question; fifth column: warehouse_name.
