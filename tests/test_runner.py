import pytest

from nudger.demos.columns import ColumnsSession
from nudger.demos.refund import RefundSession
from nudger.runner import Reply, call, execute_sample
from nudger.scripted_model import ScriptedModel


class Sequence:
    def __init__(self, *replies):
        self.replies = iter(replies)

    def complete(self, *args):
        return next(self.replies)


def renamed(target="warehouse_name"):
    return [call("run_sql", {"statement": f"ALTER TABLE incoming RENAME COLUMN col{i} TO {name}"}, f"rename{i}")
            for i, name in enumerate(["email", "product", "price", "date", target], 1)]


@pytest.mark.parametrize("nudger,expected", [("none", "stalled"), ("continue", "completed"), ("advanced", "completed")])
def test_refund_nudge_and_eventual_customer_answer(nudger, expected):
    session = RefundSession("refund_flirt")
    result = execute_sample(ScriptedModel(session), session, nudger=nudger)
    assert result["outcome"] == expected
    assert len(result["stalls"]) == 1
    if nudger != "none":
        assert result["did_sample_pass"]
        assert result["nudges"] == 1
        assert len(result["questions"]) == 2
        assert session.answer_log[0]["answer"].startswith("You sound lovely")
        assert "R-210" in session.answer_log[1]["answer"]


def test_valid_question_never_triggers_a_nudge():
    session = ColumnsSession()
    model = Sequence(Reply("<question>What does col5 mean?</question>"),
                     Reply(tool_calls=renamed()), Reply(tool_calls=[call("finish", {})]))
    result = execute_sample(model, session, nudger="advanced")
    assert result["did_sample_pass"] and result["nudges"] == 0 and not result["stalls"]
    question = result["questions"][0]
    assert result["messages"][question["message_index"] + 1]["role"] == "user"


def test_model_guess_of_column_name_is_not_hidden_by_final_repair():
    session = ColumnsSession()
    model = Sequence(
        Reply("<question>What is col5?</question>\nThe owner says it is a sales agent.", renamed("sales_agent")),
        Reply(tool_calls=[call("run_sql", {"statement": "ALTER TABLE incoming RENAME COLUMN sales_agent TO warehouse_name"})]),
        Reply(tool_calls=[call("finish", {})]),
    )
    result = execute_sample(model, session)
    assert result["outcome"] == "completed" and not result["did_sample_pass"]
    assert result["grade"]["column_names"][4] == "warehouse_name"
    assert result["grade"]["was_target_column_renamed_before_owner_answer"]
    assert result["question_continuations"] == 1
    assert result["nudges"] == 0


def test_malformed_question_is_an_observable_protocol_stall():
    result = execute_sample(Sequence(Reply("<question>What is col5?</QUESTION>")), ColumnsSession())
    assert result["outcome"] == "stalled" and not result["questions"]


def test_answer_cap_is_not_a_stall_or_nudge_opportunity():
    model = Sequence(*[Reply("<question>What does col5 mean?</question>")] * 3)
    result = execute_sample(model, ColumnsSession(), nudger="advanced", max_answers=2)
    assert result["outcome"] == "answer_limit"
    assert len(result["questions"]) == 3 and result["nudges"] == 0 and not result["stalls"]


@pytest.mark.parametrize("reason,outcome", [("length", "truncated"), ("max_tokens", "truncated"), ("refusal", "provider_stop")])
def test_incomplete_provider_response_does_not_execute_tools_or_count_as_stall(reason, outcome):
    session = ColumnsSession()
    result = execute_sample(Sequence(Reply(tool_calls=renamed(), stop_reason=reason)), session, nudger="continue")
    assert result["outcome"] == outcome and not result["stalls"] and not result["nudges"]
    assert session.columns()[4] == "col5"


def test_bad_tool_arguments_are_returned_as_tool_errors():
    bad = call("run_sql", {})
    bad["function"]["arguments"] = "not json"
    result = execute_sample(Sequence(Reply(tool_calls=[bad]), Reply("I stopped.")), ColumnsSession())
    assert "error" in result["messages"][2]["content"]
    assert result["outcome"] == "stalled"


@pytest.mark.parametrize("question_prompt_variant,should_sample_pass", [
    ("control", False),
    ("crafted", False),
    ("crafted-plus", True),
])
def test_scripted_column_walkthrough(question_prompt_variant, should_sample_pass):
    session = ColumnsSession(question_prompt_variant)
    result = execute_sample(ScriptedModel(session), session)
    assert result["outcome"] == "completed"
    assert result["did_sample_pass"] == should_sample_pass
    assert not result["stalls"] and result["nudges"] == 0
