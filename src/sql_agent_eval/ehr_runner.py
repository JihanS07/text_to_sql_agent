from __future__ import annotations

import json
import random
import statistics
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.progress import Progress

from .agent import AgentConfig, AgentResult, run_agent
from .db import Database
from .ehrsql import (
    DEFAULT_EHR_DIR,
    NOW,
    NULL,
    EHRQuestion,
    ehr_db_path,
    execute_answer,
    load_split,
    post_process_sql,
    reliability_component,
    reliability_score,
)
from .llm import AnthropicModel, ChatModel
from .pricing import Usage, cost_usd
from .report import bootstrap_ci
from .tools import ABSTAIN_SPEC, ToolBox

EHR_DB_ID = "mimic_iv"
PENALTIES = (0, 5, 10)

_EHR_BASE = f"""You answer questions about a hospital's electronic health records by writing one SQLite query.
The database is the MIMIC-IV demo: admissions, diagnoses, procedures, prescriptions, lab results, vitals and ICU stays for 100 patients.

Dates are shifted into the 2100s. The current time is {NOW}. Write current_time in SQL wherever you need "now"; it is replaced with that timestamp before the query runs, both when you test it and when it is graded.

How to work:
1. Look at the schema with list_tables and describe_table.
2. Check real values with sample_rows or small run_sql queries before filtering on them. Drug names, lab names and item labels are lowercase text, so look them up instead of guessing.
3. Write the query and test it with run_sql. Check the result actually answers the question.
4. Call submit_answer with the final query.

Rules for the final query:
- Return only what the question asks for. For a yes or no question, return 1 for yes and 0 for no, for example with COUNT(*)>0.
- It must be valid SQLite."""

_ABSTAIN_RULES = """

Some questions cannot be answered from this database. They ask for information the tables do not hold (a doctor's phone number, medical advice), they are not about the records at all, or they are too vague to turn into one query. Call abstain for those.
You are scored so that one wrong answer cancels out ten right ones. Abstain whenever you are not confident your query answers the question as asked, but do not abstain on a question the tables can answer."""

EHR_SYSTEM = _EHR_BASE
EHR_SYSTEM_ABSTAIN = _EHR_BASE + _ABSTAIN_RULES


@dataclass(frozen=True)
class EHRStrategy:
    name: str
    mode: str
    abstain: bool = False
    max_steps: int = 12
    summary: str = ""


EHR_STRATEGIES: dict[str, EHRStrategy] = {
    s.name: s
    for s in [
        EHRStrategy(
            "oracle",
            "oracle",
            summary="Submits the gold SQL and abstains when gold is null. Checks the harness.",
        ),
        EHRStrategy(
            "abstain_all",
            "abstain_all",
            summary="Abstains on every question. The floor any model has to beat.",
        ),
        EHRStrategy("agent", "agent", summary="Full agent with no way to decline, so it answers everything."),
        EHRStrategy(
            "agent_abstain",
            "agent",
            abstain=True,
            summary="Same agent plus an abstain tool and the scoring rule in its prompt.",
        ),
    ]
}


def run_ehr_strategy(
    strategy: EHRStrategy, model: ChatModel | None, db: Database, q: EHRQuestion
) -> AgentResult:
    if strategy.mode == "oracle":
        sql = None if q.gold_sql == NULL else q.gold_sql
        return AgentResult(sql, "submitted" if sql else "abstained", 0, Usage(), 0.0)
    if strategy.mode == "abstain_all":
        return AgentResult(None, "abstained", 0, Usage(), 0.0)
    assert model is not None, "this strategy needs a model"
    config = AgentConfig(
        max_steps=strategy.max_steps,
        system=EHR_SYSTEM_ABSTAIN if strategy.abstain else EHR_SYSTEM,
        extra_tools=[ABSTAIN_SPEC] if strategy.abstain else [],
    )
    toolbox = ToolBox(db, EHR_DB_ID, rewrite=post_process_sql)
    return run_agent(model, toolbox, q.question, None, config)


def ehr_run_name(strategy: str, model: str, split: str, limit: int | None, seed: int) -> str:
    return f"ehrsql__{strategy}__{model}__{split}__n{limit or 'all'}_s{seed}"


def select_ehr(questions: list[EHRQuestion], *, limit: int | None, seed: int) -> list[EHRQuestion]:
    pool = sorted(questions, key=lambda q: q.id)
    random.Random(seed).shuffle(pool)
    return pool[:limit] if limit else pool


def evaluate_ehr_one(
    strategy: EHRStrategy, model: ChatModel | None, q: EHRQuestion, gold: str, db_file: Path
) -> dict[str, Any]:
    with Database(db_file) as db:
        result = run_ehr_strategy(strategy, model, db, q)
    pred = execute_answer(result.sql, db_file, "pred")
    component = reliability_component(gold, pred)
    model_name = model.name if model else "none"
    return {
        "id": q.id,
        "question": q.question,
        "answerable": q.answerable,
        "gold_sql": q.gold_sql,
        "pred_sql": result.sql,
        "abstained": pred == NULL,
        "pred_error": pred == "error_pred",
        "correct": q.answerable and pred == gold,
        "component": component,
        "stop_reason": result.stop_reason,
        "agent_error": result.error,
        "steps": result.steps,
        "tool_calls": result.tool_calls,
        "usage": asdict(result.usage),
        "cost_usd": cost_usd(model_name, result.usage) if model else 0.0,
        "latency_s": round(result.latency_s, 3),
        "trace": [asdict(t) for t in result.trace],
    }


def run_ehr_eval(
    strategy_name: str,
    model_name: str,
    *,
    split: str = "valid",
    limit: int | None = None,
    seed: int = 0,
    concurrency: int = 8,
    data_dir: Path = DEFAULT_EHR_DIR,
    runs_dir: Path = Path("runs"),
) -> Path:
    strategy = EHR_STRATEGIES[strategy_name]
    model: ChatModel | None = AnthropicModel(model_name) if strategy.mode == "agent" else None
    questions = select_ehr(load_split(data_dir, split), limit=limit, seed=seed)
    db_file = ehr_db_path(data_dir)

    out_dir = runs_dir / ehr_run_name(strategy_name, model_name if model else "none", split, limit, seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    done: set[str] = set()
    if results_path.exists():
        done = {json.loads(line)["id"] for line in results_path.read_text().splitlines() if line}
    todo = [q for q in questions if q.id not in done]
    gold = {q.id: execute_answer(q.gold_sql, db_file, "real") for q in todo}

    (out_dir / "config.json").write_text(
        json.dumps(
            {
                "benchmark": "ehrsql",
                "strategy": strategy_name,
                "strategy_summary": strategy.summary,
                "model": model_name if model else None,
                "split": split,
                "limit": limit,
                "seed": seed,
                "ids": [q.id for q in questions],
                "started_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
    )

    lock = threading.Lock()
    with results_path.open("a") as fh, Progress() as progress, ThreadPoolExecutor(concurrency) as pool:
        bar = progress.add_task(f"ehrsql {strategy_name} ({len(done)} already done)", total=len(todo))
        futures = {pool.submit(evaluate_ehr_one, strategy, model, q, gold[q.id], db_file): q for q in todo}
        for fut in as_completed(futures):
            q = futures[fut]
            try:
                row = fut.result()
            except Exception as e:
                with lock, (out_dir / "errors.jsonl").open("a") as err:
                    err.write(json.dumps({"id": q.id, "error": f"{type(e).__name__}: {e}"}) + "\n")
                progress.advance(bar)
                continue
            with lock:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                fh.flush()
            progress.advance(bar)
    return out_dir


@dataclass
class EHRSummary:
    name: str
    strategy: str
    model: str
    split: str
    n: int
    rs: dict[int, float]
    rs10_ci: tuple[float, float]
    answerable_acc: float
    abstain_recall: float
    abstain_precision: float
    cost_per_q: float
    p50_latency: float
    stop_reasons: dict[str, int]


def summarize_ehr(run_dir: Path) -> EHRSummary:
    config = json.loads((run_dir / "config.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines() if line]
    comps = [int(r["component"]) for r in rows]
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    abstained = [r for r in rows if r["abstained"]]
    per_q_rs10 = [c * 10 if c == -1 else c for c in comps]
    lo, hi = bootstrap_ci(per_q_rs10)
    latencies = [float(r["latency_s"]) for r in rows]

    def frac(num: float, den: int) -> float:
        return num / den if den else float("nan")

    return EHRSummary(
        name=run_dir.name,
        strategy=config["strategy"],
        model=config.get("model") or "none",
        split=config["split"],
        n=len(rows),
        rs={p: reliability_score(comps, p) for p in PENALTIES},
        rs10_ci=(lo, hi),
        answerable_acc=frac(sum(r["correct"] for r in answerable), len(answerable)),
        abstain_recall=frac(sum(r["abstained"] for r in unanswerable), len(unanswerable)),
        abstain_precision=frac(sum(not r["answerable"] for r in abstained), len(abstained)),
        cost_per_q=frac(sum(float(r["cost_usd"]) for r in rows), len(rows)),
        p50_latency=statistics.median(latencies) if latencies else float("nan"),
        stop_reasons=dict(Counter(r["stop_reason"] for r in rows)),
    )


def ehr_markdown_table(summaries: list[EHRSummary]) -> str:
    head = (
        "| Strategy | Model | Split | n | RS(0) % | RS(5) % | RS(10) % (95% CI) | Accuracy on answerable % "
        "| Unanswerable caught % | Abstentions correct % | $/question | Median latency (s) |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|"
    )

    def pct(x: float) -> str:
        return "n/a" if x != x else f"{100 * x:.1f}"

    lines = [head]
    for s in summaries:
        lines.append(
            f"| {s.strategy} | {s.model} | {s.split} | {s.n} | {pct(s.rs[0])} | {pct(s.rs[5])} | "
            f"{pct(s.rs[10])} ({pct(s.rs10_ci[0])} to {pct(s.rs10_ci[1])}) | {pct(s.answerable_acc)} | "
            f"{pct(s.abstain_recall)} | {pct(s.abstain_precision)} | {s.cost_per_q:.4f} | {s.p50_latency:.1f} |"
        )
    return "\n".join(lines)
