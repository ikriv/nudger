"""Pre-canned responses used without calling a real model."""
from .runner import Reply, call


class ScriptedModel:
    def __init__(self, session):
        self.session = session
        self.index = 0

    def complete(self, system, tools, messages):
        self.index += 1
        session = self.session
        if session.demo == "refund":
            if self.index == 1:
                return Reply("I can help with your return. Shall I continue?")
            if session.known_customer_fact_names != {"reference", "reason"}:
                return Reply("<question>What is your order reference and the reason for the return?</question>")
            if session.reference not in session.looked_up_order_references:
                return Reply(tool_calls=[call("get_order", {"reference": session.reference}, f"lookup_{self.index}")])
            return Reply(tool_calls=[call("submit_decision", session.expected(), f"decision_{self.index}")])
        if self.index == 1:
            return Reply(tool_calls=[call("run_sql", {"statement": "SELECT * FROM incoming"}, "read")])
        column_labels = ["customer_email", "product_name", "item_price", "order_date", "warehouse_name"]
        if self.index == 2 and session.question_prompt_variant == "crafted-plus":
            return Reply("<question>What does col5 represent?</question>")
        if any(c.startswith("col") for c in session.columns()):
            text = ""
            if not session.did_owner_explain_target_column:
                text = "<question>What does col5 represent?</question>\nThe owner says it is the salesperson."
                column_labels[4] = "salesperson"
            rename_tool_calls = [
                call("run_sql", {"statement": f"ALTER TABLE incoming RENAME COLUMN col{i} TO {name}"},
                     f"rename_{i}")
                for i, name in enumerate(column_labels, 1)
            ]
            return Reply(text, rename_tool_calls)
        return Reply(tool_calls=[call("finish", {}, "finish")])
