from __future__ import annotations

import csv
import io
import json
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_DATA_DIR = Path("data/bird_minidev")
DEFAULT_QUESTIONS = "mini_dev_sqlite_2025.json"


@dataclass(frozen=True)
class Question:
    question_id: int
    db_id: str
    question: str
    evidence: str
    gold_sql: str
    difficulty: str


def load_questions(data_dir: Path = DEFAULT_DATA_DIR, file: str = DEFAULT_QUESTIONS) -> list[Question]:
    raw = json.loads((data_dir / file).read_text(encoding="utf-8"))
    return [
        Question(
            question_id=int(r["question_id"]),
            db_id=r["db_id"],
            question=r["question"],
            evidence=r.get("evidence") or "",
            gold_sql=r["SQL"],
            difficulty=r["difficulty"],
        )
        for r in raw
    ]


def select_questions(
    questions: list[Question],
    *,
    limit: int | None = None,
    seed: int = 0,
    db_ids: list[str] | None = None,
    question_ids: list[int] | None = None,
) -> list[Question]:
    pool = questions
    if question_ids:
        wanted = set(question_ids)
        pool = [q for q in pool if q.question_id in wanted]
    if db_ids:
        pool = [q for q in pool if q.db_id in db_ids]
    pool = sorted(pool, key=lambda q: q.question_id)
    random.Random(seed).shuffle(pool)
    return pool[:limit] if limit else pool


def db_path(db_id: str, data_dir: Path = DEFAULT_DATA_DIR) -> Path:
    return data_dir / "dev_databases" / db_id / f"{db_id}.sqlite"


def _read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@lru_cache(maxsize=64)
def column_descriptions(db_id: str, data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, list[dict[str, str]]]:
    folder = data_dir / "dev_databases" / db_id / "database_description"
    out: dict[str, list[dict[str, str]]] = {}
    if not folder.exists():
        return out
    for f in sorted(folder.glob("*.csv")):
        reader = csv.DictReader(io.StringIO(_read_text_any(f)), restkey="_extra")
        rows = []
        for r in reader:
            clean: dict[str, str] = {}
            extra: list[str] = []
            for k, v in r.items():
                values = v if isinstance(v, list) else [v]
                text = " ".join((x or "").strip() for x in values).strip()
                key = (k or "").strip()
                if key in ("", "_extra"):
                    if text:
                        extra.append(text)
                else:
                    clean[key] = text
            if extra:
                clean["value_description"] = "; ".join([clean.get("value_description", ""), *extra]).strip(
                    "; "
                )
            if clean.get("original_column_name"):
                rows.append(clean)
        out[f.stem.lower()] = rows
    return out
