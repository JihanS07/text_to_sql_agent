from sql_agent_eval.db import Database
from sql_agent_eval.scoring import execution_match


def test_row_order_does_not_matter(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        r = execution_match(
            db,
            "SELECT name FROM customers ORDER BY name DESC",
            "SELECT name FROM customers ORDER BY name",
        )
    assert r.correct


def test_column_order_matters(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        r = execution_match(db, "SELECT country, name FROM customers", "SELECT name, country FROM customers")
    assert not r.correct


def test_extra_column_is_wrong(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        r = execution_match(db, "SELECT name, id FROM customers", "SELECT name FROM customers")
    assert not r.correct


def test_failed_prediction_records_error(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        r = execution_match(db, "SELECT nope FROM customers", "SELECT name FROM customers")
    assert not r.correct
    assert r.error and "nope" in r.error


def test_missing_prediction(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        r = execution_match(db, None, "SELECT 1")
    assert not r.correct and r.error == "no SQL produced"


def test_cached_gold_rows_match_fresh_rows(shop_db_path) -> None:
    with Database(shop_db_path) as db:
        r = execution_match(db, "SELECT COUNT(*) FROM customers", "unused", gold_rows=[[3]])
    assert r.correct
