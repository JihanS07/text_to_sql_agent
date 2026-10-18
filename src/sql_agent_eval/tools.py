from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .data import DEFAULT_DATA_DIR, column_descriptions
from .db import Database, QueryResult, QueryTimeoutError, UnsafeQueryError

MAX_CELL_CHARS = 80
MAX_PREVIEW_ROWS = 20
MAX_TOOL_OUTPUT_CHARS = 6_000


def _cell(v: Any) -> str:
    s = "NULL" if v is None else str(v)
    return s if len(s) <= MAX_CELL_CHARS else s[: MAX_CELL_CHARS - 3] + "..."


def format_result(result: QueryResult) -> str:
    if not result.columns:
        return "(query returned no columns)"
    lines = [" | ".join(result.columns)]
    lines += [" | ".join(_cell(v) for v in row) for row in result.rows]
    shown = len(result.rows)
    note = f"\n({shown} row{'s' if shown != 1 else ''}"
    note += ", more rows exist, output truncated)" if result.truncated else ")"
    text = "\n".join(lines) + note
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        text = text[:MAX_TOOL_OUTPUT_CHARS] + "\n...(output cut at character limit)"
    return text


def describe_columns(db: Database, db_id: str, table: str, data_dir: Path = DEFAULT_DATA_DIR) -> str:
    text = db.create_statement(table)
    notes = column_descriptions(db_id, data_dir).get(table.lower(), [])
    if notes:
        lines = []
        for n in notes:
            parts = [n.get("column_description", ""), n.get("value_description", "")]
            desc = "; ".join(p for p in parts if p)
            if desc:
                lines.append(f"- {n['original_column_name']}: {desc}")
        if lines:
            text += "\nColumn notes:\n" + "\n".join(lines)
    return text


def schema_prompt(
    db: Database,
    db_id: str,
    *,
    sample_rows: int = 0,
    include_descriptions: bool = False,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> str:
    blocks = []
    for table in db.table_names():
        block = (
            describe_columns(db, db_id, table, data_dir)
            if include_descriptions
            else db.create_statement(table)
        )
        if sample_rows:
            block += f"\n-- {sample_rows} example rows:\n" + format_result(db.sample_rows(table, sample_rows))
        blocks.append(block)
    return "\n\n".join(blocks)


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_tables",
        "description": "List every table in the database.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "describe_table",
        "description": (
            "Show a table's CREATE statement (columns, types, keys) and the dataset's "
            "notes on what each column means and how values are encoded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "Exact table name."}},
            "required": ["table"],
        },
    },
    {
        "name": "sample_rows",
        "description": "Show the first few rows of a table, to see real value formats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "n": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
            },
            "required": ["table"],
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run one read-only SQLite SELECT query and see up to 20 result rows. "
            "Use it to check value formats, test joins and verify your answer before submitting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
    {
        "name": "submit_answer",
        "description": (
            "Submit the final SQLite query that answers the question. Call this exactly once, "
            "when you are confident. The query's full result is what gets graded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
]


class ToolBox:
    def __init__(self, db: Database, db_id: str, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        self.db = db
        self.db_id = db_id
        self.data_dir = data_dir
        self.executed_sql: list[str] = []
        self._handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            "list_tables": lambda _: "\n".join(self.db.table_names()),
            "describe_table": lambda a: describe_columns(self.db, self.db_id, a["table"], self.data_dir),
            "sample_rows": lambda a: format_result(self.db.sample_rows(a["table"], int(a.get("n", 3)))),
            "run_sql": self._run_sql,
        }

    def _run_sql(self, args: dict[str, Any]) -> str:
        sql = args["sql"]
        result = self.db.execute(sql, max_rows=MAX_PREVIEW_ROWS, timeout_s=15)
        self.executed_sql.append(sql)
        return format_result(result)

    def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        handler = self._handlers.get(name)
        if handler is None:
            return f"Unknown tool {name!r}.", True
        try:
            return handler(args), False
        except KeyError as e:
            return f"No such table: {e}. Call list_tables to see valid names.", True
        except (UnsafeQueryError, QueryTimeoutError) as e:
            return f"Rejected: {e}", True
        except Exception as e:
            return f"{type(e).__name__}: {e}", True


def tool_input_preview(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False)[:300]
