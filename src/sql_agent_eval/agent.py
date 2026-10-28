from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .llm import ChatModel
from .pricing import Usage
from .tools import TOOL_SPECS, ToolBox, tool_input_preview

AGENT_SYSTEM = """You answer questions about a SQLite database by writing one SQL query.

How to work:
1. Look at the schema with list_tables and describe_table. Read the column notes, they explain codes and units.
2. Check real values with sample_rows or small run_sql queries before filtering on them (spelling, case, date formats).
3. Write the query and test it with run_sql. Fix errors and look at the result: does it actually answer the question?
4. Call submit_answer with the final query.

Rules for the final query:
- Return only the columns the question asks for, in the order it asks for them. No extra columns.
- If a hint is given, follow it. It defines how the question's terms map to columns and formulas.
- It must be valid SQLite."""

SINGLE_SYSTEM = """You answer questions about a SQLite database by writing one SQL query.

Database schema:
{schema}

Rules:
- Return only the columns the question asks for, in the order it asks for them. No extra columns.
- If a hint is given, follow it. It defines how the question's terms map to columns and formulas.
- Reply with the SQLite query in a ```sql code block and nothing else."""


def user_prompt(question: str, evidence: str | None) -> str:
    text = f"Question: {question}"
    if evidence:
        text += f"\nHint: {evidence}"
    return text


_SQL_BLOCK = re.compile(r"```(?:sql|sqlite)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str | None:
    blocks = _SQL_BLOCK.findall(text)
    if blocks:
        return blocks[-1].strip().rstrip(";").strip() or None
    stripped = text.strip()
    if re.match(r"(?is)^(select|with)\b", stripped):
        return stripped.rstrip(";").strip()
    return None


@dataclass
class AgentConfig:
    max_steps: int = 12
    max_output_tokens: int = 2048
    token_budget: int = 400_000
    allowed_tools: list[str] | None = None
    system: str = AGENT_SYSTEM
    extra_tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TraceStep:
    tool: str
    input: str
    output: str
    is_error: bool


@dataclass
class AgentResult:
    sql: str | None
    stop_reason: str
    steps: int
    usage: Usage
    latency_s: float
    trace: list[TraceStep] = field(default_factory=list)
    error: str | None = None

    @property
    def tool_calls(self) -> int:
        return len(self.trace)


def run_agent(
    model: ChatModel,
    toolbox: ToolBox,
    question: str,
    evidence: str | None,
    config: AgentConfig | None = None,
) -> AgentResult:
    cfg = config or AgentConfig()
    tools = [t for t in TOOL_SPECS if cfg.allowed_tools is None or t["name"] in cfg.allowed_tools]
    tools += cfg.extra_tools
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt(question, evidence)}]
    usage = Usage()
    trace: list[TraceStep] = []
    start = time.monotonic()

    def finish(sql: str | None, reason: str, steps: int, error: str | None = None) -> AgentResult:
        return AgentResult(sql, reason, steps, usage, time.monotonic() - start, trace, error)

    for step in range(1, cfg.max_steps + 1):
        try:
            turn = model.complete(cfg.system, messages, tools=tools, max_tokens=cfg.max_output_tokens)
        except Exception as e:
            return finish(_fallback(toolbox), "model_error", step, f"{type(e).__name__}: {e}")
        usage.add(turn.usage)
        messages.append({"role": "assistant", "content": turn.content})

        if not turn.tool_calls:
            return finish(extract_sql(turn.text) or _fallback(toolbox), "no_tool_call", step)

        results: list[dict[str, Any]] = []
        for call in turn.tool_calls:
            if call.name == "submit_answer":
                trace.append(TraceStep("submit_answer", tool_input_preview(call.input), "", False))
                return finish(str(call.input.get("sql", "")).strip() or None, "submitted", step)
            if call.name == "abstain":
                trace.append(TraceStep("abstain", tool_input_preview(call.input), "", False))
                return finish(None, "abstained", step)
            output, is_error = toolbox.call(call.name, call.input)
            trace.append(TraceStep(call.name, tool_input_preview(call.input), output[:500], is_error))
            results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": output, "is_error": is_error}
            )
        messages.append({"role": "user", "content": results})

        if usage.input_tokens + usage.cache_read_input_tokens + usage.output_tokens > cfg.token_budget:
            return finish(_fallback(toolbox), "budget", step)

    return finish(_fallback(toolbox), "max_steps", cfg.max_steps)


def _fallback(toolbox: ToolBox) -> str | None:
    return toolbox.executed_sql[-1] if toolbox.executed_sql else None
