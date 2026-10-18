from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .db import Database, QueryTimeoutError

SCORING_TIMEOUT_S = 60.0
GOLD_CACHE_FILE = "gold_results.jsonl"


@dataclass
class ScoreResult:
    correct: bool
    error: str | None = None
    gold_error: str | None = None


def canonical_rows(rows: list[tuple[Any, ...]] | list[list[Any]]) -> set[tuple[Any, ...]]:
    return {tuple(json.loads(json.dumps(list(r), default=str))) for r in rows}


@lru_cache(maxsize=4)
def load_gold_cache(path: Path) -> dict[int, list[list[Any]]]:
    if not path.exists():
        return {}
    out: dict[int, list[list[Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("rows") is not None:
            out[int(rec["question_id"])] = rec["rows"]
    return out


def execution_match(
    db: Database,
    predicted_sql: str | None,
    gold_sql: str,
    *,
    gold_rows: list[list[Any]] | None = None,
) -> ScoreResult:
    if gold_rows is None:
        try:
            gold_rows = [list(r) for r in db.execute(gold_sql, timeout_s=SCORING_TIMEOUT_S, check=False).rows]
        except Exception as e:
            return ScoreResult(correct=False, gold_error=f"{type(e).__name__}: {e}")
    if not predicted_sql or not predicted_sql.strip():
        return ScoreResult(correct=False, error="no SQL produced")
    try:
        pred = db.execute(predicted_sql, timeout_s=SCORING_TIMEOUT_S).rows
    except QueryTimeoutError as e:
        return ScoreResult(correct=False, error=f"timeout: {e}")
    except Exception as e:
        return ScoreResult(correct=False, error=f"{type(e).__name__}: {e}")
    return ScoreResult(correct=canonical_rows(pred) == canonical_rows(gold_rows))
