from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .data import DEFAULT_DATA_DIR, DEFAULT_QUESTIONS
from .ehr_runner import EHR_STRATEGIES, ehr_markdown_table, run_ehr_eval, summarize_ehr
from .ehrsql import DEFAULT_EHR_DIR
from .report import compare as compare_runs
from .report import load_run, markdown_table, summarize
from .runner import run_eval
from .strategies import STRATEGIES

app = typer.Typer(help="Text-to-SQL agent and evaluation harness on BIRD Mini-Dev.", no_args_is_help=True)
console = Console()


def _load_dotenv() -> None:
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


@app.command(help="List the strategies in the ablation.")
def strategies() -> None:
    t = Table("name", "mode", "what changes")
    for s in STRATEGIES.values():
        t.add_row(s.name, s.mode, s.summary)
    console.print(t)


@app.command(help="Run one strategy and score it.")
def run(
    strategy: Annotated[str, typer.Option(help="Strategy name, see `sqlagent strategies`.")] = "agent",
    model: Annotated[str, typer.Option(help="Claude model ID.")] = "claude-haiku-5-5",
    limit: Annotated[
        int | None, typer.Option(help="Number of questions (seeded sample). Omit for all.")
    ] = None,
    seed: int = 0,
    concurrency: int = 8,
    hint: Annotated[bool, typer.Option(help="Give the model BIRD's evidence hint.")] = True,
    db: Annotated[list[str] | None, typer.Option(help="Restrict to these db_ids.")] = None,
    questions_file: str = DEFAULT_QUESTIONS,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> None:
    _load_dotenv()
    if strategy not in STRATEGIES:
        raise typer.BadParameter(f"unknown strategy {strategy!r}")
    out = run_eval(
        strategy,
        model,
        limit=limit,
        seed=seed,
        concurrency=concurrency,
        use_evidence=hint,
        data_dir=data_dir,
        questions_file=questions_file,
        db_ids=db,
    )
    console.print(markdown_table([summarize(out)]))
    console.print(f"\nResults in {out}")


@app.command("cache-gold", help="Run every gold query once and cache the results.")
def cache_gold(
    data_dir: Path = DEFAULT_DATA_DIR,
    questions_file: str = DEFAULT_QUESTIONS,
    timeout: Annotated[float, typer.Option(help="Seconds allowed per gold query.")] = 900.0,
) -> None:
    import time

    from .data import db_path, load_questions
    from .db import Database
    from .scoring import GOLD_CACHE_FILE

    questions = load_questions(data_dir, questions_file)
    path = data_dir / GOLD_CACHE_FILE
    slow = []
    with path.open("w", encoding="utf-8") as fh:
        for q in sorted(questions, key=lambda q: q.question_id):
            rec: dict[str, object] = {"question_id": q.question_id}
            start = time.monotonic()
            try:
                with Database(db_path(q.db_id, data_dir)) as db:
                    rec["rows"] = [
                        list(r) for r in db.execute(q.gold_sql, timeout_s=timeout, check=False).rows
                    ]
            except Exception as e:
                rec["rows"], rec["error"] = None, f"{type(e).__name__}: {e}"
            rec["seconds"] = round(time.monotonic() - start, 2)
            if rec["seconds"] > 10:  # type: ignore[operator]
                slow.append((q.question_id, rec["seconds"]))
            fh.write(json.dumps(rec, default=str) + "\n")
    console.print(f"Cached {len(questions)} gold results to {path}. Slow (>10s): {slow}")


@app.command(help="Summary table across runs.")
def report(
    runs: Annotated[
        list[Path] | None, typer.Argument(help="Run directories. Default: all under runs/.")
    ] = None,
    out: Annotated[Path | None, typer.Option(help="Also write the table to this markdown file.")] = None,
    readme: Annotated[
        bool, typer.Option(help="Replace the table between the README's results markers.")
    ] = False,
) -> None:
    import re

    dirs = runs or sorted(p for p in Path("runs").iterdir() if (p / "results.jsonl").exists())
    table = markdown_table([summarize(d) for d in dirs])
    console.print(table)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(table + "\n")
    if readme:
        path = Path("README.md")
        text = path.read_text()
        pattern = re.compile(r"(<!-- results:start -->\n).*?(\n<!-- results:end -->)", re.S)
        if not pattern.search(text):
            raise typer.BadParameter("README.md has no results markers")
        path.write_text(pattern.sub(lambda m: m.group(1) + table + m.group(2), text))


@app.command(help="Paired comparison of two runs.")
def compare(run_a: Path, run_b: Path) -> None:
    console.print(compare_runs(run_a, run_b))


@app.command(help="Export wrong answers to a CSV for labelling.")
def failures(
    run_dir: Path,
    out: Annotated[Path | None, typer.Option(help="CSV path. Default: <run>/failures.csv")] = None,
) -> None:
    _, rows = load_run(run_dir)
    wrong = [r for r in rows if not r.get("correct")]
    path = out or run_dir / "failures.csv"
    fields = [
        "question_id", "db_id", "difficulty", "question", "evidence", "gold_sql", "pred_sql",
        "exec_error", "stop_reason", "tool_calls", "label", "notes",
    ]  # fmt: skip
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in wrong:
            w.writerow({**r, "label": "", "notes": ""})
    console.print(f"{len(wrong)} failures written to {path}")


@app.command(help="Print one question's full trace.")
def show(run_dir: Path, question_id: int) -> None:
    _, rows = load_run(run_dir)
    row = next((r for r in rows if r["question_id"] == question_id), None)
    if row is None:
        raise typer.BadParameter(f"question {question_id} not in run")
    console.print_json(json.dumps(row, default=str))


@app.command("ehrsql-run", help="Run one strategy on EHRSQL 2024 (MIMIC-IV demo) and score it.")
def ehrsql_run(
    strategy: Annotated[
        str, typer.Option(help="oracle, abstain_all, agent or agent_abstain.")
    ] = "agent_abstain",
    model: Annotated[str, typer.Option(help="Claude model ID.")] = "claude-haiku-5-5",
    split: Annotated[str, typer.Option(help="valid or test.")] = "valid",
    limit: Annotated[int | None, typer.Option(help="Number of questions (seeded sample).")] = None,
    seed: int = 0,
    concurrency: int = 8,
    data_dir: Path = DEFAULT_EHR_DIR,
) -> None:
    _load_dotenv()
    if strategy not in EHR_STRATEGIES:
        raise typer.BadParameter(f"unknown strategy {strategy!r}")
    out = run_ehr_eval(
        strategy, model, split=split, limit=limit, seed=seed, concurrency=concurrency, data_dir=data_dir
    )
    console.print(ehr_markdown_table([summarize_ehr(out)]))
    console.print(f"\nResults in {out}")


@app.command("ehrsql-report", help="Summary table across EHRSQL runs.")
def ehrsql_report(
    runs: Annotated[
        list[Path] | None, typer.Argument(help="Run directories. Default: all ehrsql runs.")
    ] = None,
    readme: Annotated[
        bool, typer.Option(help="Replace the table between the README's ehrsql markers.")
    ] = False,
) -> None:
    import re

    dirs = runs or sorted(p for p in Path("runs").glob("ehrsql__*") if (p / "results.jsonl").exists())
    table = ehr_markdown_table([summarize_ehr(d) for d in dirs])
    console.print(table)
    if readme:
        path = Path("README.md")
        text = path.read_text()
        pattern = re.compile(r"(<!-- ehrsql:start -->\n)(?:.*?\n)?(<!-- ehrsql:end -->)", re.S)
        if not pattern.search(text):
            raise typer.BadParameter("README.md has no ehrsql markers")
        path.write_text(pattern.sub(lambda m: m.group(1) + table + "\n" + m.group(2), text))


if __name__ == "__main__":
    app()
