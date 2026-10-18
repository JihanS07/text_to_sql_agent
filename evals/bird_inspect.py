from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer, stderr
from inspect_ai.solver import Generate, TaskState, solver

from sql_agent_eval.agent import user_prompt
from sql_agent_eval.data import DEFAULT_DATA_DIR, Question, db_path, load_questions, select_questions
from sql_agent_eval.db import Database
from sql_agent_eval.llm import AnthropicModel, ChatModel
from sql_agent_eval.pricing import cost_usd
from sql_agent_eval.scoring import GOLD_CACHE_FILE, execution_match, load_gold_cache
from sql_agent_eval.strategies import STRATEGIES, run_strategy

REPO_ROOT = Path(__file__).resolve().parent.parent


@solver
def sql_agent(strategy: str, model_id: str, hint: bool, data_dir: str):
    strat = STRATEGIES[strategy]
    model: ChatModel | None = None if strat.mode == "oracle" else AnthropicModel(model_id)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        q = Question(**state.metadata["question"])

        def work():
            with Database(db_path(q.db_id, Path(data_dir))) as db:
                return run_strategy(strat, model, db, q, use_evidence=hint, data_dir=Path(data_dir))

        result = await asyncio.to_thread(work)
        state.output = ModelOutput.from_content(model=model_id, content=result.sql or "")
        state.metadata["agent"] = {
            "stop_reason": result.stop_reason,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "usage": asdict(result.usage),
            "cost_usd": cost_usd(model_id, result.usage) if model else 0.0,
            "trace": [asdict(t) for t in result.trace],
            "error": result.error,
        }
        return state

    return solve


@scorer(metrics=[accuracy(), stderr()])
def execution_accuracy(data_dir: str):
    cache = load_gold_cache(Path(data_dir) / GOLD_CACHE_FILE)

    async def score(state: TaskState, target: Target) -> Score:
        q = Question(**state.metadata["question"])
        sql = state.output.completion

        def work():
            with Database(db_path(q.db_id, Path(data_dir))) as db:
                return execution_match(db, sql, target.text, gold_rows=cache.get(q.question_id))

        r = await asyncio.to_thread(work)
        return Score(
            value=CORRECT if r.correct else INCORRECT,
            answer=sql,
            explanation=r.error or r.gold_error,
            metadata={"difficulty": q.difficulty, "db_id": q.db_id},
        )

    return score


@task
def bird_minidev(
    strategy: str = "agent",
    model_id: str = "claude-haiku-5-5",
    limit: int | None = None,
    seed: int = 0,
    hint: bool = True,
    data_dir: str = str(DEFAULT_DATA_DIR),
) -> Task:
    if not Path(data_dir).is_absolute():
        data_dir = str(REPO_ROOT / data_dir)
    questions = select_questions(load_questions(Path(data_dir)), limit=limit, seed=seed)
    samples = [
        Sample(
            id=q.question_id,
            input=user_prompt(q.question, q.evidence if hint else None),
            target=q.gold_sql,
            metadata={"question": asdict(q), "difficulty": q.difficulty},
        )
        for q in questions
    ]
    return Task(
        dataset=samples,
        solver=sql_agent(strategy, model_id, hint, data_dir),
        scorer=execution_accuracy(data_dir),
    )
