import sqlite3
import pytest
from pageql.reactive import ReactiveTable


def test_insert_error_message_has_no_params():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    with pytest.raises(Exception) as exc:
        rt.insert("INSERT INTO items(nonexistent) VALUES (1)", {})
    assert "with params" not in str(exc.value)
