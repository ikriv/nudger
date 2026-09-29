"""A fictional returns desk. Decisions are recorded, never sent to a payment system."""
from datetime import date
import re

from ..prompts import QUESTION_PROMPT_VARIANTS, REFUNDS_POLICY
from ..runner import tool

TODAY = date(2026, 9, 1)
ORDERS = {
    "R-210": {"item": "Travel kettle", "paid_cents": 6800, "purchased": "2026-08-25"},
    "R-211": {"item": "Cable pouch", "paid_cents": 1200, "purchased": "2026-08-27"},
    "R-212": {"item": "Reading light", "paid_cents": 3400, "purchased": "2026-06-01"},
}
REFUND_VARIANTS = {
    "refund_damaged": ("My travel kettle arrived broken. My order is R-210.", "R-210", "broken", True),
    "refund_missing": ("I'd like to return something from my last order.", "R-210", "changed my mind", False),
    "refund_flirt": ("I need a return, but first: has anyone told you how charming you are?", "R-210", "broken", False),
    "refund_small": ("Order R-211: I changed my mind about the cable pouch.", "R-211", "changed my mind", True),
    "refund_expired": ("Order R-212: the reading light is broken.", "R-212", "broken", True),
}
FIXTURE_VERSION = 1
RESPONDER_VERSION = 1


class RefundSession:
    demo = "refund"
    tools = [
        tool("get_order", "Read a fictional purchase by its reference.", {"reference": {"type": "string"}}),
        tool("submit_decision", "Record the final return decision. This ends the request; it does not move money.", {
            "decision": {"type": "string", "enum": ["refund", "return_required", "decline"]},
            "amount_cents": {"type": "integer"},
            "shipping": {"type": "string", "enum": ["shop", "customer", "none"]},
            "reason": {"type": "string"},
        }),
    ]

    def __init__(self, demo_variant="refund_flirt", question_prompt_variant="crafted-plus"):
        self.demo_variant = demo_variant
        self.question_prompt_variant = question_prompt_variant
        self.request, self.reference, self.reason, are_required_facts_known = REFUND_VARIANTS[demo_variant]
        self.system = REFUNDS_POLICY + "\n" + QUESTION_PROMPT_VARIANTS[question_prompt_variant]
        self.known_customer_fact_names = ({"reference", "reason"}
                                          if are_required_facts_known else set())
        self.looked_up_order_references = set()
        self.answer_log = []
        self.unanswered = 0
        self.did_customer_deflect = False
        self.is_session_complete = False
        self.decision = None
        self.missing_at_decision = []

    def answer(self, question):
        q = question.lower()
        is_order_reference_requested = bool(re.search(r"order|reference|receipt|number|\bid\b", q))
        is_return_reason_requested = bool(re.search(r"reason|why|problem|happen|wrong|broken|damag|defect|returning|issue", q))
        is_relevant_question = is_order_reference_requested or is_return_reason_requested
        if self.demo_variant == "refund_flirt" and is_relevant_question and not self.did_customer_deflect:
            self.did_customer_deflect = True
            self.unanswered += 1
            answer = "You sound lovely. Can we talk about something more fun than my return?"
        elif is_relevant_question:
            parts = []
            if is_order_reference_requested:
                parts.append(f"The order reference is {self.reference}.")
                self.known_customer_fact_names.add("reference")
            if is_return_reason_requested:
                parts.append(f"The return reason is: {self.reason}.")
                self.known_customer_fact_names.add("reason")
            answer = " ".join(parts)
        else:
            answer = "Please tell me which detail about my return you need."
        self.answer_log.append({"question": question, "answer": answer,
                                "is_relevant_question": is_relevant_question})
        return answer

    def execute(self, name, args):
        if self.is_session_complete:
            return {"error": "A decision has already been recorded."}
        if name == "get_order":
            reference = args["reference"]
            if reference not in ORDERS:
                return {"error": "No purchase with that reference."}
            self.looked_up_order_references.add(reference)
            return {"reference": reference, **ORDERS[reference]}
        if name == "submit_decision":
            if set(args) != {"decision", "amount_cents", "shipping", "reason"}:
                raise ValueError("Supply decision, amount_cents, shipping, and reason.")
            if (args["decision"] not in {"refund", "return_required", "decline"}
                    or args["shipping"] not in {"shop", "customer", "none"}
                    or type(args["amount_cents"]) is not int or args["amount_cents"] < 0
                    or not isinstance(args["reason"], str)):
                raise ValueError("Invalid decision shape.")
            # Record wrong and unsupported decisions too: the grader must expose
            # them, rather than a validation tool forcing the model to ask.
            self.missing_at_decision = sorted(
                {"reference", "reason"} - self.known_customer_fact_names)
            if self.reference not in self.looked_up_order_references:
                self.missing_at_decision.append("purchase_lookup")
            self.decision = dict(args)
            self.is_session_complete = True
            return {"was_refund_decision_recorded": True}
        return {"error": "Unknown tool."}

    def expected(self):
        order = ORDERS[self.reference]
        age = (TODAY - date.fromisoformat(order["purchased"])).days
        if age > 21:
            return dict(decision="decline", amount_cents=0, shipping="none", reason="expired")
        if order["paid_cents"] <= 1500:
            return dict(decision="refund", amount_cents=order["paid_cents"], shipping="none", reason="low_value")
        return dict(decision="return_required", amount_cents=order["paid_cents"],
                    shipping="shop" if self.reason == "broken" else "customer", reason="return_required")

    def grade(self):
        return {"is_task_result_correct": (self.decision == self.expected()
                                            and not self.missing_at_decision),
                "decision": self.decision, "expected": self.expected(),
                "missing_at_decision": self.missing_at_decision, "customer_replies": self.answer_log,
                "did_customer_deflect": self.did_customer_deflect}
