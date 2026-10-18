from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("bird")
    db_dir = root / "dev_databases" / "shop"
    (db_dir / "database_description").mkdir(parents=True)
    conn = sqlite3.connect(db_dir / "shop.sqlite")
    conn.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL,
                             FOREIGN KEY (customer_id) REFERENCES customers(id));
        INSERT INTO customers VALUES (1,'Ana','CZ'),(2,'Ben','DE'),(3,'Cy','CZ');
        INSERT INTO orders VALUES (1,1,10.0),(2,1,5.5),(3,2,7.0),(4,3,1.0);
        """
    )
    conn.commit()
    conn.close()
    (db_dir / "database_description" / "customers.csv").write_text(
        "original_column_name,column_name,column_description,data_format,value_description,\n"
        'country,country,country code,text,,"CZ means Czech Republic"\n',
        encoding="utf-8",
    )
    questions = [
        {
            "question_id": 1,
            "db_id": "shop",
            "question": "How many customers are in CZ?",
            "evidence": "CZ refers to country = 'CZ'",
            "SQL": "SELECT COUNT(*) FROM customers WHERE country = 'CZ'",
            "difficulty": "simple",
        },
        {
            "question_id": 2,
            "db_id": "shop",
            "question": "Total order amount per customer name?",
            "evidence": "",
            "SQL": "SELECT c.name, SUM(o.amount) FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.name",
            "difficulty": "moderate",
        },
    ]
    (root / "questions.json").write_text(json.dumps(questions))
    return root


@pytest.fixture
def shop_db_path(data_dir: Path) -> Path:
    return data_dir / "dev_databases" / "shop" / "shop.sqlite"
