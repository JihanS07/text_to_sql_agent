import sqlite3

import pytest

from sql_agent_eval.db import Database, QueryTimeoutError, UnsafeQueryError, check_read_only


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers",
        "DROP TABLE customers",
        "UPDATE customers SET name = 'x'",
        "INSERT INTO customers VALUES (9,'z','US')",
        "PRAGMA table_info(customers)",
        "ATTACH DATABASE 'x.db' AS other",
        "SELECT 1; DROP TABLE customers",
    ],
)
def test_check_read_only_rejects_writes(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        check_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM customers",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT 1 UNION SELECT 2",
        "SELECT IIF(country = 'CZ', 1, 0) FROM customers",
    ],
)
def test_check_read_only_allows_queries(sql: str) -> None:
    check_read_only(sql)


def test_connection_refuses_writes_even_without_check(shop_db_path) -> None:
    with Database(shop_db_path) as db, pytest.raises(sqlite3.OperationalError):
        db.execute("DELETE FROM customers", check=False)


def test_row_cap_marks_truncation(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        r = db.execute("SELECT * FROM orders", max_rows=2)
    assert len(r.rows) == 2
    assert r.truncated


def test_timeout_interrupts_runaway_query(shop_db_path) -> None:
    runaway = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT max(i) FROM n"
    with Database(shop_db_path) as db, pytest.raises(QueryTimeoutError):
        db.execute(runaway, timeout_s=0.3)


def test_schema_helpers(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        assert db.table_names() == ["customers", "orders"]
        assert "CREATE TABLE customers" in db.create_statement("customers")
        assert len(db.sample_rows("customers", 2).rows) == 2
        with pytest.raises(KeyError):
            db.sample_rows("nope")
