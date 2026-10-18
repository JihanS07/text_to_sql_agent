from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.progress import Progress

from .data import DEFAULT_DATA_DIR, DEFAULT_QUESTIONS, Question, db_path, load_questions, select_questions
from .db import Database
from .llm import AnthropicModel, ChatModel
from .pricing import cost_usd
from .scoring import GOLD_CACHE_FILE, execution_match, load_gold_cache
from .strategies import STRATEGIES, Strategy, run_strategy


def run_name(strategy: str, model: str, use_evidence: bool, limit: int | None, seed: int) -> str:
    ev = "hint" if use_evidence else "nohint"
    return f"{strategy}__{model}__{ev}__n{limit or 'all'}_s{seed}"


def evaluate_one(
    strategy: Strategy,
    model: ChatModel | None,
    q: Question,
    *,
    use_evidence: bool,
    data_dir: Path,
) -> dict[str, Any]:
    gold_rows = load_gold_cache(data_dir / GOLD_CACHE_FILE).get(q.question_id)
    with Database(db_path(q.db_id, data_dir)) as db:
        result = run_strategy(strategy, model, db, q, use_evidence=use_evidence, data_dir=data_dir)
        score = execution_match(db, result.sql, q.gold_sql, gold_rows=gold_rows)
    model_name = model.name if model else "none"
    return {
        "question_id": q.question_id,
        "db_id": q.db_id,
        "difficulty": q.difficulty,
        "question": q.question,
        "evidence": q.evidence if use_evidence else "",
        "gold_sql": q.gold_sql,
        "pred_sql": result.sql,
        "correct": score.correct,
        "exec_error": score.error,
        "gold_error": score.gold_error,
        "stop_reason": result.stop_reason,
        "agent_error": result.error,
        "steps": result.steps,
        "tool_calls": result.tool_calls,
        "usage": asdict(result.usage),
        "cost_usd": cost_usd(model_name, result.usage) if model else 0.0,
        "latency_s": round(result.latency_s, 3),
        "trace": [asdict(t) for t in result.trace],
    }


def run_eval(
    strategy_name: str,
    model_name: str,
    *,
    limit: int | None = None,
    seed: int = 0,
    concurrency: int = 8,
    use_evidence: bool = True,
    data_dir: Path = DEFAULT_DATA_DIR,
    questions_file: str = DEFAULT_QUESTIONS,
    runs_dir: Path = Path("runs"),
    db_ids: list[str] | None = None,
) -> Path:
    strategy = STRATEGIES[strategy_name]
    model: ChatModel | None = None if strategy.mode == "oracle" else AnthropicModel(model_name)
    questions = select_questions(
        load_questions(data_dir, questions_file), limit=limit, seed=seed, db_ids=db_ids
    )

    out_dir = runs_dir / run_name(strategy_name, model_name if model else "none", use_evidence, limit, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    done: set[int] = set()
    if results_path.exists():
        done = {json.loads(line)["question_id"] for line in results_path.read_text().splitlines() if line}
    todo = [q for q in questions if q.question_id not in done]

    (out_dir / "config.json").write_text(
        json.dumps(
            {
                "strategy": strategy_name,
                "strategy_summary": strategy.summary,
                "model": model_name if model else None,
                "use_evidence": use_evidence,
                "limit": limit,
                "seed": seed,
                "questions_file": questions_file,
                "question_ids": [q.question_id for q in questions],
                "started_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )

    lock = threading.Lock()
    with results_path.open("a") as fh, Progress() as progress, ThreadPoolExecutor(concurrency) as pool:
        bar = progress.add_task(f"{strategy_name} ({len(done)} already done)", total=len(todo))
        futures = {
            pool.submit(evaluate_one, strategy, model, q, use_evidence=use_evidence, data_dir=data_dir): q
            for q in todo
        }
        for fut in as_completed(futures):
            q = futures[fut]
            try:
                row = fut.result()
            except Exception as e:
                with lock, (out_dir / "errors.jsonl").open("a") as err:
                    err.write(
                        json.dumps({"question_id": q.question_id, "error": f"{type(e).__name__}: {e}"}) + "\n"
                    )
                progress.advance(bar)
                continue
            with lock:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                fh.flush()
            progress.advance(bar)
    return out_dir
