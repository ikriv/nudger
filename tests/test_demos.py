import pytest

from nudger.demos.columns import ColumnsSession
from nudger.demos.refund import RefundSession


def test_flirt_does_not_supply_unasked_details_or_deflect_forever():
    session = RefundSession("refund_flirt")
    assert "lovely" in session.answer("What is your order reference?")
    assert not session.known_customer_fact_names
    assert "R-210" in session.answer("What is your order reference?")
    assert session.known_customer_fact_names == {"reference"}
    assert "broken" in session.answer("Why are you returning it?")
    assert session.known_customer_fact_names == {"reference", "reason"}


def test_wrong_refund_is_recorded_then_graded_not_rejected_into_correctness():
    session = RefundSession("refund_flirt")
    assert session.execute("submit_decision", session.expected()) == {
        "was_refund_decision_recorded": True,
    }
    assert session.is_session_complete
    assert not session.grade()["is_task_result_correct"]
    assert set(session.grade()["missing_at_decision"]) == {"reference", "reason", "purchase_lookup"}


@pytest.mark.parametrize("demo_variant,decision,shipping,cents", [
    ("refund_damaged", "return_required", "shop", 6800),
    ("refund_missing", "return_required", "customer", 6800),
    ("refund_small", "refund", "none", 1200),
    ("refund_expired", "decline", "none", 0),
])
def test_refund_policy(demo_variant, decision, shipping, cents):
    session = RefundSession(demo_variant)
    expected = session.expected()
    assert (expected["decision"], expected["shipping"], expected["amount_cents"]) == (decision, shipping, cents)
    session.answer("What is the order reference and the return reason?")
    session.execute("get_order", {"reference": session.reference})
    session.execute("submit_decision", expected)
    assert session.grade()["is_task_result_correct"]


@pytest.mark.parametrize("sql", [
    "DELETE FROM incoming", "UPDATE incoming SET col5='invented'", "DROP TABLE incoming",
    "ATTACH DATABASE ':memory:' AS other", "PRAGMA writable_schema=1",
    "WITH x AS (SELECT 1) DELETE FROM incoming", "SELECT load_extension('missing')",
])
def test_column_tool_is_read_only_except_for_renames(sql):
    session = ColumnsSession()
    assert "error" in session.execute("run_sql", {"statement": sql})
    assert session.is_data_preserved()


def test_wrong_business_name_can_finish_and_fail_semantic_grade():
    session = ColumnsSession()
    for n, name in enumerate(["email", "item", "cost", "date", "sales_agent"], 1):
        assert session.execute(
            "run_sql", {"statement": f"ALTER TABLE incoming RENAME COLUMN col{n} TO {name}"}
        ) == {"was_sql_statement_successful": True}
    assert session.execute("finish", {}) == {"was_export_completion_recorded": True}
    assert session.is_data_preserved()
    assert not session.grade()["is_task_result_correct"]
    assert session.grade()["was_target_column_renamed_before_owner_answer"]


def test_unknown_question_does_not_receive_hidden_warehouse_meaning():
    session = ColumnsSession()
    assert "warehouse" not in session.answer("May I continue?")
    assert not session.did_owner_explain_target_column
    assert "warehouse" in session.answer("What does the fifth column represent?")


def test_fixture_is_identical_across_question_prompt_variants():
    assert ColumnsSession("control").rows == ColumnsSession("crafted").rows == ColumnsSession("crafted-plus").rows


def test_refund_fixture_is_identical_across_question_prompt_variants():
    sessions = [
        RefundSession("refund_flirt", question_prompt_variant)
        for question_prompt_variant in ["control", "crafted", "crafted-plus"]
    ]
    assert {session.request for session in sessions} == {sessions[0].request}
    assert len({session.system for session in sessions}) == 3


def test_compound_question_receives_each_requested_fact():
    session = ColumnsSession()
    answer = session.answer("Is col3 a unit price or total, and what does col5 mean?")
    assert "item price" in answer and "warehouse" in answer
    assert "email" not in answer


def test_other_column_question_does_not_leak_target():
    session = ColumnsSession()
    assert session.answer("What does the third column represent?") == "Column 3 is the item price."
    assert not session.did_owner_explain_target_column


def test_known_target_in_followup_does_not_hide_other_question():
    session = ColumnsSession()
    session.answer("What is col5?")
    answer = session.answer("I understand col5. But what does col3 represent?")
    assert "item price" in answer
