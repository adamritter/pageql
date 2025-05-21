import sqlite3
import types
import sys
from pathlib import Path

# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

import pytest

from pageql.pageql import evalone
from pageql.reactive import DerivedSignal, Tables


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    return conn


def test_evalone_simple_param():
    conn = sqlite3.connect(":memory:")
    params = {"foo": 42}
    assert evalone(conn, ":foo", params) == 42


def test_evalone_dotted_param():
    conn = sqlite3.connect(":memory:")
    params = {"user__name": "Alice"}
    assert evalone(conn, ":user.name", params) == "Alice"


def test_evalone_sql_expression():
    conn = _db()
    conn.execute("INSERT INTO items(name) VALUES ('x')")
    result = evalone(conn, "name from items where id=1", {})
    assert result == "x"


def test_evalone_multiple_columns_error():
    conn = _db()
    conn.execute("INSERT INTO items(name) VALUES ('a')")
    with pytest.raises(ValueError):
        evalone(conn, "* from items", {})


def test_evalone_reactive_param_returns_signal():
    conn = sqlite3.connect(":memory:")
    params = {"foo": 1}
    sig = evalone(conn, ":foo", params, reactive=True)
    assert isinstance(sig, DerivedSignal)
    assert sig.value == 1
    assert params["foo"] is sig


def test_evalone_reactive_sql_updates():
    conn = _db()
    conn.execute("INSERT INTO items(name) VALUES ('a')")
    tables = Tables(conn)
    sig = evalone(conn, "name from items where id=1", {}, reactive=True, tables=tables)
    assert isinstance(sig, DerivedSignal)
    assert sig.value.value == "a"

    rt = tables._get("items")
    rt.update("UPDATE items SET name='b' WHERE id=1", {})
    assert sig.value.value == "b"


def test_evalone_reactive_table_and_param_dependency():
    conn = _db()
    conn.execute("INSERT INTO items(id, name) VALUES (1, 'initial_name')")
    sql = "SELECT name FROM items WHERE id = :my_id"
    params = {"my_id": 1}
    tables = Tables(conn)
    sig = evalone(conn, sql, params, reactive=True, tables=tables)
    assert sig.value.value == "initial_name"

    rt = tables._get("items")
    rt.update("UPDATE items SET name='updated_name' WHERE id=1", {})
    assert sig.value.value == "updated_name"

    rt.insert("INSERT INTO items(id, name) VALUES (2, 'another_name')", {})
    param_sig = params["my_id"]
    param_sig.value = 2
    assert sig.value.value == "another_name"

