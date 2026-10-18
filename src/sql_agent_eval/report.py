from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DIFFICULTIES = ("simple", "moderate", "challenging")


def load_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = json.loads((run_dir / "config.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines() if line]
    return config, rows


def bootstrap_ci(
    values: list[int], *, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float]:
    if not values:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(n_boot))
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return lo, hi


def mcnemar_exact_p(only_a: int, only_b: int) -> float:
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


@dataclass
class RunSummary:
    name: str
    strategy: str
    model: str
    hint: bool
    n: int
    ex: float
    ci: tuple[float, float]
    by_difficulty: dict[str, float]
    mean_tool_calls: float
    cost_per_q: float
    total_cost: float
    p50_latency: float
    stop_reasons: dict[str, int]
    exec_error_rate: float
    gold_errors: int


def summarize(run_dir: Path) -> RunSummary:
    config, rows = load_run(run_dir)
    correct = [int(bool(r["correct"])) for r in rows]
    by_diff = {}
    for d in DIFFICULTIES:
        sub = [int(bool(r["correct"])) for r in rows if r.get("difficulty") == d]
        by_diff[d] = sum(sub) / len(sub) if sub else math.nan
    stops: dict[str, int] = {}
    for r in rows:
        stops[r.get("stop_reason", "?")] = stops.get(r.get("stop_reason", "?"), 0) + 1
    costs = [r.get("cost_usd") or 0.0 for r in rows]
    lat = [r.get("latency_s", 0.0) for r in rows]
    n = len(rows)
    return RunSummary(
        name=run_dir.name,
        strategy=config["strategy"],
        model=config.get("model") or "none",
        hint=config.get("use_evidence", True),
        n=n,
        ex=sum(correct) / n if n else math.nan,
        ci=bootstrap_ci(correct),
        by_difficulty=by_diff,
        mean_tool_calls=statistics.fmean([r.get("tool_calls", 0) for r in rows]) if rows else 0.0,
        cost_per_q=statistics.fmean(costs) if rows else 0.0,
        total_cost=sum(costs),
        p50_latency=statistics.median(lat) if lat else 0.0,
        stop_reasons=stops,
        exec_error_rate=sum(1 for r in rows if r.get("exec_error")) / n if n else 0.0,
        gold_errors=sum(1 for r in rows if r.get("gold_error")),
    )


def _pct(x: float) -> str:
    return "n/a" if math.isnan(x) else f"{100 * x:.1f}"


def markdown_table(summaries: list[RunSummary]) -> str:
    head = (
        "| Strategy | Model | Hint | n | EX % (95% CI) | Simple | Moderate | Challenging "
        "| Tool calls/q | Exec errors | $/question | Median latency (s) |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|"
    )
    lines = [head]
    for s in summaries:
        lines.append(
            f"| {s.strategy} | {s.model} | {'yes' if s.hint else 'no'} | {s.n} "
            f"| {_pct(s.ex)} ({_pct(s.ci[0])}-{_pct(s.ci[1])}) "
            f"| {_pct(s.by_difficulty['simple'])} | {_pct(s.by_difficulty['moderate'])} "
            f"| {_pct(s.by_difficulty['challenging'])} | {s.mean_tool_calls:.1f} "
            f"| {_pct(s.exec_error_rate)}% | {s.cost_per_q:.4f} | {s.p50_latency:.1f} |"
        )
    return "\n".join(lines)


def compare(run_a: Path, run_b: Path) -> str:
    _, rows_a = load_run(run_a)
    _, rows_b = load_run(run_b)
    a = {r["question_id"]: bool(r["correct"]) for r in rows_a}
    b = {r["question_id"]: bool(r["correct"]) for r in rows_b}
    shared = sorted(set(a) & set(b))
    both = sum(a[q] and b[q] for q in shared)
    only_a = sum(a[q] and not b[q] for q in shared)
    only_b = sum(b[q] and not a[q] for q in shared)
    neither = len(shared) - both - only_a - only_b
    diffs = [int(b[q]) - int(a[q]) for q in shared]
    rng = random.Random(0)
    boots = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(2000)) if diffs else []
    ci = (boots[50], boots[1949]) if boots else (math.nan, math.nan)
    delta = statistics.fmean(diffs) if diffs else math.nan
    return (
        f"Paired comparison on {len(shared)} shared questions\n"
        f"  A = {run_a.name}\n  B = {run_b.name}\n"
        f"  both right {both}, only A {only_a}, only B {only_b}, neither {neither}\n"
        f"  B - A = {_pct(delta)} points (95% paired bootstrap CI {_pct(ci[0])} to {_pct(ci[1])})\n"
        f"  McNemar exact p = {mcnemar_exact_p(only_a, only_b):.4f}"
    )
