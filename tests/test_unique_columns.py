import sys
from pathlib import Path
import sqlite3

# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageql.reactive import ReactiveTable


def test_reactive_table_unique_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE items(id INTEGER PRIMARY KEY, "
        "email TEXT UNIQUE, phone TEXT, UNIQUE(phone))"
    )
    rt = ReactiveTable(conn, "items")
    assert rt.unique_columns == {"id", "email", "phone"}
