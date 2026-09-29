# Method

## One loop, two questions

The runner calls PydanticAI's model API with the current conversation and the demo's tools.
It records the whole visible response, executes its tool calls in order, and then:

1. Ends if the demo has recorded completion.
2. Routes a nonempty `<question>...</question>` to the demo's responder, and adds
   the actual reply as a subsequent user message.
3. Continues after tool results.
4. Otherwise records an unfinished text-only response as a stall, and sends the
   selected nudge if there is one and the nudge allowance remains.

A valid unanswered question is never nudged. Exhausting the answer allowance
ends with `answer_limit`; it does not grant permission to guess. Malformed tags
remain visible in a stalled transcript. Inspect those separately from idle
permission-seeking or premature wrap-ups.

Output truncation, unexpected provider stop reasons, transport errors, and request
limits are not classified as natural stalls. The evaluation layer retries only
transient failures under the documented retry policy; exhausted failures remain
recorded as infrastructure-error samples and do not enter behavioral rates.
Retries restart the demo session but remain attempts within the same sample. The
sample audit retains each attempt's transcript, usage, error, and estimated cost.

The runner does not hide a question plus action in the same response: the tools
execute before the real person replies. The grader can therefore detect an early
unsupported action that a later correction would otherwise conceal. Completion
tool calls end the job by contract; final prose is not required.

## Refund scoring

The fixed date is 2026-09-01. All orders, prices, names, and customer messages are
fictional. The customer script deflects once in `refund_flirt`, then supplies only the
requested facts. It does not supply a guessed answer to the agent's own question.

A successful sample must obtain the customer facts, look up the purchase, and record
the correct policy decision. A well-formed but wrong decision is accepted by the
tool and fails the grader: validation does not coach the model toward the answer.

Customer replies are selected by a small visible keyword router. They are not a
simulation of general human conversation. Unmatched questions get a request for
clarification; review router behavior when diagnosing failures. The included demo
variants are resolvable, so prematurely declaring insufficient information fails.

## Column scoring

Prompts see identical rows within each demo variant. The secret meaning of col5 is kept
in the responder, outside the model's initial context. Column names can be wrong
and still satisfy the tool's completion check; correctness is evaluated separately.

A successful sample must preserve the rows, obtain the actual owner answer, and use
`warehouse_name` without an earlier rename of col5. This operational criterion is
strict: a provisional generic name also counts as an early rename. It must not be
described automatically as fabrication of a specific business meaning. The exact
rename and its timing are saved so a reviewer can distinguish those situations.

Other column meanings are not comprehensively graded. The comparison concerns the
unknown fifth field, not arbitrary semantic inference over a spreadsheet.

## What the comparisons can establish

Both matrices can vary the question-prompt variant and the nudge after natural
unfinished stops. Neither script forces a real model to stall, fabricate an
answer, or display a particular improvement.

Small samples are demonstrations, not general failure-rate estimates. A model may
finish every sample without a nudge. No-stall results do not establish that two
nudgers are equivalent. A good final table alone does not establish that the
model waited properly earlier.

Reports distinguish `ended stalled` (the sample's final outcome) from
`encountered stall` (at least one unfinished response occurred before the sample
ended, including samples recovered by a nudge).

`--scripted` uses pre-canned responses instead of calling a real model. It explains
the mechanics, but its scores must not appear in a model-results table. Fresh API
samples are needed for these prompts and fixtures.

For publication, show per-scenario sample sizes, model IDs/settings, all
transcripts, infrastructure failures, and both intermediate and final errors.
Do not select only a favorable sample or merge older experiment results into
the current configuration.
