from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class UnsafeQueryError(ValueError):
    pass


class QueryTimeoutError(RuntimeError):
    pass


def check_read_only(sql: str) -> None:
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError:
        return
    if len(statements) != 1:
        raise UnsafeQueryError(f"expected exactly one statement, got {len(statements)}")
    statement = statements[0]
    if isinstance(statement, _WRITE_OR_ADMIN):
        raise UnsafeQueryError(f"only SELECT queries are allowed, got {type(statement).__name__.upper()}")


_WRITE_OR_ADMIN: tuple[type, ...] = tuple(
    cls
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Drop",
        "Create",
        "Alter",
        "Command",
        "Pragma",
        "Attach",
        "Detach",
        "Merge",
        "TruncateTable",
        "Transaction",
    )
    if (cls := getattr(exp, name, None)) is not None
)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool
    elapsed_s: float
    row_count_seen: int = field(default=0)


class Database:
    def __init__(self, path: str | Path, *, timeout_s: float = 30.0) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.timeout_s = timeout_s
        uri = f"file:{self.path.resolve()}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.execute("PRAGMA query_only = ON")
        self._conn.text_factory = lambda b: b.decode("utf-8", errors="replace")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def execute(
        self,
        sql: str,
        *,
        max_rows: int | None = None,
        timeout_s: float | None = None,
        check: bool = True,
    ) -> QueryResult:
        if check:
            check_read_only(sql)
        limit = self.timeout_s if timeout_s is None else timeout_s
        deadline = time.monotonic() + limit

        def _progress() -> int:
            return 1 if time.monotonic() > deadline else 0

        self._conn.set_progress_handler(_progress, 10_000)
        start = time.monotonic()
        try:
            cursor = self._conn.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            if max_rows is None:
                rows = cursor.fetchall()
                truncated = False
            else:
                rows = cursor.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                rows = rows[:max_rows]
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e):
                raise QueryTimeoutError(f"query exceeded {limit:.0f}s") from e
            raise
        finally:
            self._conn.set_progress_handler(None, 0)
        return QueryResult(
            columns=columns,
            rows=[tuple(r) for r in rows],
            truncated=truncated,
            elapsed_s=time.monotonic() - start,
            row_count_seen=len(rows),
        )

    def table_names(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    def create_statement(self, table: str) -> str:
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if row is None:
            raise KeyError(table)
        return str(row[0])

    def sample_rows(self, table: str, n: int = 3) -> QueryResult:
        if table not in self.table_names():
            raise KeyError(table)
        quoted = table.replace('"', '""')
        return self.execute(f'SELECT * FROM "{quoted}" LIMIT {int(n)}', check=False)
