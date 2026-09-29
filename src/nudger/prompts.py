"""All model-facing instructions used by the demos."""

QUESTION_PROTOCOL = (
    "To contact the person responsible for this task, write your question inside "
    "<question> and </question>. The application forwards only the text inside "
    "those tags. Other assistant text goes into the activity log."
)

CAREFUL_QUESTION_PROTOCOL = QUESTION_PROTOCOL + (
    "\nDistinguish observations from facts supplied by the user or tools. A plausible "
    "pattern does not establish a missing fact. Ask for necessary missing facts rather "
    "than assuming them."
)

WAITING_QUESTION_PROTOCOL = CAREFUL_QUESTION_PROTOCOL + (
    "\nThe application displays your tagged question to the responsible person. End "
    "your response immediately after </question>. Wait for a later user message with "
    "their answer before doing more work. Do not write an imagined reply or call tools "
    "in the response that asks the question."
)

QUESTION_PROMPT_VARIANTS = {
    "control": QUESTION_PROTOCOL,
    "crafted": CAREFUL_QUESTION_PROTOCOL,
    "crafted-plus": WAITING_QUESTION_PROTOCOL,
}

COLUMNS_ROLE = "You prepare incoming tabular exports for a small shop."
COLUMNS_REQUEST = (
    "Inspect the SQLite table incoming and give all five columns descriptive names "
    "that reflect their meaning. Preserve every row and value. Call finish once the "
    "renaming is complete."
)

REFUNDS_POLICY = """You staff a fictional returns desk. Today is 2026-09-01.
Resolve the customer's request using this policy, and record the decision with
submit_decision. Ordinary progress text does not record a decision.

Obtain the order reference and the return reason from the customer. Look up the
reference with get_order; use the recorded price and date. If a detail is still
missing after three relevant unanswered questions, decline with reason
insufficient_information.

Purchases older than 21 days: decline, zero cents, no return shipping, reason expired.
Otherwise, a price of 1500 cents or less: refund the full price, no return shipping,
reason low_value. For other purchases: return_required for the full price, reason
return_required. The shop pays return shipping for broken or incorrect items;
the customer pays when they changed their mind.

Finish the request without asking for permission to perform routine steps.
"""
