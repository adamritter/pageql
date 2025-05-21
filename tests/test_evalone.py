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
from pageql.reactive import DerivedSignal, DependentValue, Tables


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
    assert isinstance(sig, DependentValue)
    assert sig.value == "a"

    rt = tables._get("items")
    rt.update("UPDATE items SET name='b' WHERE id=1", {})
    assert sig.value == "b"


def test_evalone_reactive_param_and_table_updates():
    conn = _db()
    conn.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    tables = Tables(conn)
    params = {"rid": 1}
    sig = evalone(
        conn,
        "name from items where id=:rid",
        params,
        reactive=True,
        tables=tables,
    )
    assert isinstance(sig, DependentValue)
    assert sig.value == "a"

    params["rid"].set_value(2)
    assert sig.value == "b"

    rt = tables._get("items")
    rt.update("UPDATE items SET name='c' WHERE id=2", {})
    assert sig.value == "c"

