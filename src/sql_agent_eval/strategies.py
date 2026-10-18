from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .agent import SINGLE_SYSTEM, AgentConfig, AgentResult, extract_sql, run_agent, user_prompt
from .data import DEFAULT_DATA_DIR, Question
from .db import Database
from .llm import ChatModel
from .pricing import Usage
from .tools import ToolBox, schema_prompt


@dataclass(frozen=True)
class Strategy:
    name: str
    mode: str
    sample_rows: int = 0
    descriptions: bool = False
    agent_tools: tuple[str, ...] | None = None
    max_steps: int = 12
    summary: str = ""


STRATEGIES: dict[str, Strategy] = {
    s.name: s
    for s in [
        Strategy("oracle", "oracle", summary="Submits the gold SQL. Checks the harness scores 100%."),
        Strategy("single_schema", "single", summary="One call. Prompt holds CREATE statements only."),
        Strategy("single_rows", "single", sample_rows=3, summary="+ 3 example rows per table."),
        Strategy(
            "single_rows_desc",
            "single",
            sample_rows=3,
            descriptions=True,
            summary="+ BIRD's column descriptions.",
        ),
        Strategy(
            "agent_no_exec",
            "agent",
            agent_tools=("list_tables", "describe_table", "sample_rows", "submit_answer"),
            summary="Agent that explores the schema but cannot run its own queries.",
        ),
        Strategy("agent", "agent", summary="Full agent: explore, run queries, fix errors, submit."),
    ]
}


def run_strategy(
    strategy: Strategy,
    model: ChatModel | None,
    db: Database,
    question: Question,
    *,
    use_evidence: bool = True,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> AgentResult:
    evidence = question.evidence if use_evidence else None

    if strategy.mode == "oracle":
        return AgentResult(question.gold_sql, "submitted", 0, Usage(), 0.0)

    assert model is not None, "this strategy needs a model"

    if strategy.mode == "single":
        start = time.monotonic()
        schema = schema_prompt(
            db,
            question.db_id,
            sample_rows=strategy.sample_rows,
            include_descriptions=strategy.descriptions,
            data_dir=data_dir,
        )
        try:
            turn = model.complete(
                SINGLE_SYSTEM.format(schema=schema),
                [{"role": "user", "content": user_prompt(question.question, evidence)}],
                max_tokens=2048,
            )
        except Exception as e:
            return AgentResult(None, "model_error", 1, Usage(), time.monotonic() - start, error=str(e))
        sql = extract_sql(turn.text)
        return AgentResult(sql, "submitted" if sql else "no_sql", 1, turn.usage, time.monotonic() - start)

    config = AgentConfig(
        max_steps=strategy.max_steps,
        allowed_tools=list(strategy.agent_tools) if strategy.agent_tools else None,
    )
    toolbox = ToolBox(db, question.db_id, data_dir)
    return run_agent(model, toolbox, question.question, evidence, config)
