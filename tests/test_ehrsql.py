from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sql_agent_eval.db import Database
from sql_agent_eval.ehr_runner import (
    EHR_STRATEGIES,
    evaluate_ehr_one,
    run_ehr_eval,
    summarize_ehr,
)
from sql_agent_eval.ehrsql import (
    NOW,
    NULL,
    canonical_answer,
    execute_answer,
    load_split,
    post_process_sql,
    reliability_component,
    reliability_score,
)
from sql_agent_eval.llm import ScriptedModel, tool_turn
from sql_agent_eval.tools import ToolBox


@pytest.fixture
def ehr_dir(tmp_path: Path) -> Path:
    conn = sqlite3.connect(tmp_path / "mimic_iv.sqlite")
    conn.executescript(
        """
        CREATE TABLE admissions (hadm_id INTEGER, subject_id INTEGER, admittime TEXT);
        INSERT INTO admissions VALUES (1, 100, '2100-12-30 08:00:00'), (2, 100, '2099-01-05 10:00:00'),
                                      (3, 200, '2100-06-01 09:00:00');
        """
    )
    conn.commit()
    conn.close()
    questions = {
        "a1": (
            "How many times was patient 100 admitted?",
            "SELECT COUNT(*) FROM admissions WHERE subject_id = 100",
        ),
        "a2": (
            "Was patient 200 admitted in the last 2 days?",
            "SELECT COUNT(*)>0 FROM admissions WHERE subject_id = 200 "
            "AND datetime(admittime) >= datetime(current_time,'-2 day')",
        ),
        "u1": ("What is the phone number of patient 100's doctor?", NULL),
    }
    split = tmp_path / "valid"
    split.mkdir()
    (split / "data.json").write_text(
        json.dumps({"version": "test", "data": [{"id": k, "question": v[0]} for k, v in questions.items()]})
    )
    (split / "label.json").write_text(json.dumps({k: v[1] for k, v in questions.items()}))
    return tmp_path


def test_post_process_pins_the_clock():
    sql = "SELECT 1 WHERE datetime(x) >= datetime(current_time,'-1 year') AND d = current_date"
    out = post_process_sql(sql)
    assert f"'{NOW}'" in out and "'2100-12-31'" in out and "current_time" not in out


def test_post_process_converts_mysql_intervals_and_vital_ranges():
    assert post_process_sql("SELECT DATE_SUB(NOW(), INTERVAL 1 MONTH)") == (
        f"SELECT datetime('{NOW}', '-1 month')"
    )
    out = post_process_sql("SELECT * FROM v WHERE v.x < heart_rate_lower OR v.x > heart_rate_upper")
    assert "60.0" in out and "100.0" in out


def test_canonical_answer_rounds_sorts_and_caps():
    assert canonical_answer([(2.00049,), (1,)]) == "[['1.0'], ['2.0']]"
    assert canonical_answer([(i,) for i in range(150)]).count("[") == 101
    assert canonical_answer("[['1']]") == canonical_answer([(1,)]) == "[['1.0']]"


@pytest.mark.parametrize(
    ("gold", "pred", "expected"),
    [
        ("[['1']]", "[['1']]", 1),
        ("[['1']]", NULL, 0),
        ("[['1']]", "[['0']]", -1),
        ("[['1']]", "error_pred", -1),
        (NULL, "[['1']]", -1),
        (NULL, NULL, 1),
    ],
)
def test_reliability_component_matches_the_official_cases(gold: str, pred: str, expected: int):
    assert reliability_component(gold, pred) == expected


def test_reliability_score_penalty():
    comps = [1] * 9 + [-1]
    assert reliability_score(comps, 0) == pytest.approx(0.9)
    assert reliability_score(comps, 10) == pytest.approx(-0.1)


def test_gold_needs_post_processing(ehr_dir: Path):
    db = ehr_dir / "mimic_iv.sqlite"
    q = next(q for q in load_split(ehr_dir, "valid") if q.id == "a2")
    assert execute_answer(q.gold_sql, db, "real") == "[['0.0']]"
    raw = sqlite3.connect(db).execute(q.gold_sql).fetchall()
    assert canonical_answer(raw) == "[['1.0']]"


def test_run_sql_applies_the_rewrite(ehr_dir: Path):
    with Database(ehr_dir / "mimic_iv.sqlite") as db:
        box = ToolBox(db, "mimic_iv", rewrite=post_process_sql)
        out, is_error = box.call("run_sql", {"sql": "SELECT datetime(current_time)"})
    assert not is_error and NOW in out


def test_agent_can_abstain_and_is_scored_for_it(ehr_dir: Path):
    db = ehr_dir / "mimic_iv.sqlite"
    q = next(q for q in load_split(ehr_dir, "valid") if q.id == "u1")
    model = ScriptedModel(
        [tool_turn("list_tables", {}), tool_turn("abstain", {"reason": "no phone numbers"})]
    )
    row = evaluate_ehr_one(EHR_STRATEGIES["agent_abstain"], model, q, NULL, db)
    assert row["stop_reason"] == "abstained" and row["abstained"] and row["component"] == 1
    assert row["pred_sql"] is None


def test_abstain_tool_only_offered_to_the_abstain_strategy(ehr_dir: Path):
    db = ehr_dir / "mimic_iv.sqlite"
    q = next(q for q in load_split(ehr_dir, "valid") if q.id == "a1")
    gold = execute_answer(q.gold_sql, db, "real")
    for name, offered in [("agent", False), ("agent_abstain", True)]:
        model = ScriptedModel(
            [tool_turn("submit_answer", {"sql": "SELECT COUNT(*) FROM admissions WHERE subject_id = 100"})]
        )
        captured: list[list[str]] = []
        original = model.complete

        def spy(system, messages, tools=None, max_tokens=2048, _orig=original, _cap=captured):
            _cap.append([t["name"] for t in tools or []])
            return _orig(system, messages, tools, max_tokens)

        model.complete = spy  # type: ignore[method-assign]
        row = evaluate_ehr_one(EHR_STRATEGIES[name], model, q, gold, db)
        assert row["correct"] and row["component"] == 1
        assert ("abstain" in captured[0]) is offered


def test_baselines_end_to_end(ehr_dir: Path, tmp_path: Path):
    runs = tmp_path / "runs"
    oracle = summarize_ehr(run_ehr_eval("oracle", "none", data_dir=ehr_dir, runs_dir=runs, concurrency=1))
    floor = summarize_ehr(run_ehr_eval("abstain_all", "none", data_dir=ehr_dir, runs_dir=runs, concurrency=1))
    assert oracle.rs[10] == 1.0 and oracle.answerable_acc == 1.0
    assert floor.rs[10] == pytest.approx(1 / 3) and floor.abstain_recall == 1.0
