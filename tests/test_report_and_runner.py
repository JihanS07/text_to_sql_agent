import json
from pathlib import Path

from sql_agent_eval.data import load_questions, select_questions
from sql_agent_eval.report import bootstrap_ci, compare, mcnemar_exact_p, summarize
from sql_agent_eval.runner import run_eval


def test_mcnemar_known_values() -> None:
    assert mcnemar_exact_p(0, 0) == 1.0
    assert abs(mcnemar_exact_p(0, 5) - 0.0625) < 1e-12
    assert mcnemar_exact_p(3, 3) == 1.0


def test_bootstrap_ci_brackets_the_mean() -> None:
    values = [1] * 70 + [0] * 30
    lo, hi = bootstrap_ci(values)
    assert lo < 0.7 < hi
    assert lo > 0.55 and hi < 0.85


def test_selection_is_deterministic(data_dir: Path) -> None:
    qs = load_questions(data_dir, "questions.json")
    a = [q.question_id for q in select_questions(qs, limit=1, seed=3)]
    b = [q.question_id for q in select_questions(qs, limit=1, seed=3)]
    assert a == b


def test_oracle_run_end_to_end(data_dir: Path, tmp_path: Path) -> None:
    out = run_eval("oracle", "none", data_dir=data_dir, questions_file="questions.json", runs_dir=tmp_path)
    s = summarize(out)
    assert s.n == 2 and s.ex == 1.0
    run_eval("oracle", "none", data_dir=data_dir, questions_file="questions.json", runs_dir=tmp_path)
    lines = (out / "results.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["stop_reason"] == "submitted"
    assert "Paired comparison on 2" in compare(out, out)
