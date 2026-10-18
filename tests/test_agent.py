from sql_agent_eval.agent import AgentConfig, extract_sql, run_agent
from sql_agent_eval.db import Database
from sql_agent_eval.llm import ScriptedModel, text_turn, tool_turn
from sql_agent_eval.tools import ToolBox

GOLD = "SELECT COUNT(*) FROM customers WHERE country = 'CZ'"


def test_happy_path_explore_test_submit(shop_db_path, data_dir) -> None:
    model = ScriptedModel(
        [
            tool_turn("list_tables", {}, "a"),
            tool_turn("describe_table", {"table": "customers"}, "b"),
            tool_turn("run_sql", {"sql": GOLD}, "c"),
            tool_turn("submit_answer", {"sql": GOLD}, "d"),
        ]
    )
    with Database(shop_db_path) as db:
        result = run_agent(model, ToolBox(db, "shop", data_dir), "How many in CZ?", "hint")
    assert result.stop_reason == "submitted"
    assert result.sql == GOLD
    assert result.steps == 4
    assert [t.tool for t in result.trace] == ["list_tables", "describe_table", "run_sql", "submit_answer"]
    assert "Czech Republic" in result.trace[1].output
    last_request = model.requests[-1]
    assert last_request[-1]["content"][0]["tool_use_id"] == "c"
    assert result.usage.calls == 4


def test_tool_errors_go_back_to_the_model(shop_db_path, data_dir) -> None:
    model = ScriptedModel(
        [
            tool_turn("run_sql", {"sql": "DROP TABLE customers"}, "a"),
            tool_turn("submit_answer", {"sql": GOLD}, "b"),
        ]
    )
    with Database(shop_db_path) as db:
        result = run_agent(model, ToolBox(db, "shop", data_dir), "q", None)
    assert result.trace[0].is_error
    sent = model.requests[1][-1]["content"][0]
    assert sent["is_error"] is True and "Rejected" in sent["content"]


def test_prose_answer_is_parsed(shop_db_path, data_dir) -> None:
    model = ScriptedModel([text_turn(f"Here you go:\n```sql\n{GOLD};\n```")])
    with Database(shop_db_path) as db:
        result = run_agent(model, ToolBox(db, "shop", data_dir), "q", None)
    assert result.stop_reason == "no_tool_call"
    assert result.sql == GOLD


def test_max_steps_falls_back_to_last_successful_query(shop_db_path, data_dir) -> None:
    model = ScriptedModel(
        [
            tool_turn("run_sql", {"sql": "SELECT 1"}, "a"),
            tool_turn("run_sql", {"sql": "SELECT broken syntax here"}, "b"),
            tool_turn("list_tables", {}, "c"),
        ]
    )
    with Database(shop_db_path) as db:
        result = run_agent(model, ToolBox(db, "shop", data_dir), "q", None, AgentConfig(max_steps=3))
    assert result.stop_reason == "max_steps"
    assert result.sql == "SELECT 1"


def test_model_error_is_recorded(shop_db_path, data_dir) -> None:
    class Broken:
        name = "broken"

        def complete(self, *a, **k):
            raise ConnectionError("network down")

    with Database(shop_db_path) as db:
        result = run_agent(Broken(), ToolBox(db, "shop", data_dir), "q", None)
    assert result.stop_reason == "model_error"
    assert result.error and "network down" in result.error


def test_allowed_tools_are_enforced_in_specs(shop_db_path, data_dir) -> None:
    seen = {}

    class Spy(ScriptedModel):
        def complete(self, system, messages, tools=None, max_tokens=2048):
            seen["tools"] = [t["name"] for t in tools or []]
            return super().complete(system, messages, tools, max_tokens)

    model = Spy([tool_turn("submit_answer", {"sql": GOLD})])
    with Database(shop_db_path) as db:
        run_agent(
            model, ToolBox(db, "shop", data_dir), "q", None, AgentConfig(allowed_tools=["submit_answer"])
        )
    assert seen["tools"] == ["submit_answer"]


def test_extract_sql_variants() -> None:
    assert extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert extract_sql("first\n```sql\nSELECT 1\n```\nthen\n```sql\nSELECT 2\n```") == "SELECT 2"
    assert extract_sql("SELECT a FROM b;") == "SELECT a FROM b"
    assert extract_sql("I am not sure.") is None
