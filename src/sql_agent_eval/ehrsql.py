from __future__ import annotations

import json
import re
import sqlite3
from ast import literal_eval
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_EHR_DIR = Path("data/ehrsql")
NULL = "null"
NOW = "2100-12-31 23:59:00"
CURRENT_DATE = "2100-12-31"
CURRENT_TIME = "23:59:00"
MAX_COMPARED_ROWS = 100


@dataclass(frozen=True)
class EHRQuestion:
    id: str
    question: str
    gold_sql: str

    @property
    def answerable(self) -> bool:
        return self.gold_sql != NULL


def load_split(data_dir: Path = DEFAULT_EHR_DIR, split: str = "valid") -> list[EHRQuestion]:
    data = json.loads((data_dir / split / "data.json").read_text(encoding="utf-8"))["data"]
    labels: dict[str, str] = json.loads((data_dir / split / "label.json").read_text(encoding="utf-8"))
    return [EHRQuestion(d["id"], d["question"], labels[d["id"]]) for d in data]


def ehr_db_path(data_dir: Path = DEFAULT_EHR_DIR) -> Path:
    return data_dir / "mimic_iv.sqlite"


# Ported from the EHRSQL 2024 scoring program (CC BY 4.0), so scores match the official ones.
_VITAL_RANGES = {
    "temperature": (35.5, 38.1),
    "sao2": (95.0, 100.0),
    "heart rate": (60.0, 100.0),
    "respiration": (12.0, 18.0),
    "systolic bp": (90.0, 120.0),
    "diastolic bp": (60.0, 90.0),
    "mean bp": (60.0, 110.0),
}
_MYSQL_INTERVAL = re.compile(r"(DATE_SUB|DATE_ADD)\((\w+\(\)|'[^']+')[, ]+ INTERVAL (\d+) (MONTH|YEAR|DAY)\)")


def _interval_to_sqlite(m: re.Match[str]) -> str:
    func, date, number, unit = m.group(1), m.group(2), m.group(3), m.group(4).lower()
    unit = unit.rstrip("s") if number == "1" else (unit if unit.endswith("s") else unit + "s")
    sign = "-" if func == "DATE_SUB" else "+"
    return f"datetime({date}, '{sign}{number} {unit}')"


def post_process_sql(query: str) -> str:
    query = re.sub("[ ]+", " ", query.replace("\n", " ")).strip()
    query = query.replace("> =", ">=").replace("< =", "<=").replace("! =", "!=")
    query = _MYSQL_INTERVAL.sub(_interval_to_sqlite, query)
    query = query.replace("current_time", f"'{NOW}'").replace("current_date", f"'{CURRENT_DATE}'")
    query = query.replace("'now'", f"'{NOW}'").replace("NOW()", f"'{NOW}'")
    query = query.replace("CURDATE()", f"'{CURRENT_DATE}'").replace("CURTIME()", f"'{CURRENT_TIME}'")
    lower = re.findall("[ \n]+([a-zA-Z0-9_]+_lower)", query)
    upper = re.findall("[ \n]+([a-zA-Z0-9_]+_upper)", query)
    if lower and upper:
        names = set(
            re.findall("([a-zA-Z0-9_]+)_lower", lower[0]) + re.findall("([a-zA-Z0-9_]+)_upper", upper[0])
        )
        if len(names) == 1:
            vital = names.pop().replace("_", " ")
            if vital in _VITAL_RANGES:
                lo, hi = _VITAL_RANGES[vital]
                query = query.replace(lower[0], f"{lo}").replace(upper[0], f"{hi}")
    return query.replace("%y", "%Y").replace("%j", "%J")


def _cell(item: Any) -> str:
    try:
        return str(round(float(item), 3))
    except Exception:
        return str(item)


def canonical_answer(rows: list[tuple[Any, ...]] | list[list[Any]] | str) -> str:
    if isinstance(rows, str):
        try:
            rows = literal_eval(rows)
        except (ValueError, SyntaxError):
            return rows
        if isinstance(rows, str):
            return rows
    return str(sorted([[_cell(c) for c in row] for row in rows])[:MAX_COMPARED_ROWS])


def execute_answer(sql: str | None, db_path: Path, tag: str = "pred") -> str:
    if sql is None or sql.strip() == "" or sql.strip() == NULL:
        return NULL
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode(errors="ignore")
    try:
        rows = con.execute(post_process_sql(sql)).fetchall()
    except Exception:
        return f"error_{tag}"
    finally:
        con.close()
    return canonical_answer(rows)


def reliability_component(gold: str, pred: str) -> int:
    if gold != NULL:
        if pred == NULL:
            return 0
        return 1 if pred == gold else -1
    return 1 if pred == NULL else -1


def reliability_score(components: list[int], penalty: float) -> float:
    if not components:
        return float("nan")
    return sum(c * penalty if c == -1 else c for c in components) / len(components)
