import sqlite3
import sys
from pathlib import Path

# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from pageql.database import evalone
from pageql.reactive import DerivedSignal, Tables, Signal
import sqlglot


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
    assert sig.value == "a"

    rt = tables._get("items")
    rt.update("UPDATE items SET name='b' WHERE id=1", {})
    assert sig.value == "b"


def test_evalone_reactive_dotted_param():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sessions(token TEXT PRIMARY KEY, user_id INTEGER)")
    conn.execute("INSERT INTO sessions(token, user_id) VALUES ('abc', 1)")
    tables = Tables(conn)
    sig = evalone(
        conn,
        "user_id from sessions where token=:cookies.session",
        {"cookies__session": "abc"},
        reactive=True,
        tables=tables,
    )
    assert sig.value == 1

    rt = tables._get("sessions")
    rt.update("UPDATE sessions SET user_id=2 WHERE token='abc'", {})
    assert sig.value == 2

def test_evalone_reactive_uses_expr(monkeypatch):
    conn = _db()
    conn.execute("INSERT INTO items(name) VALUES ('z')")
    tables = Tables(conn)
    expr = sqlglot.parse_one("SELECT name FROM items WHERE id = 1", read="sqlite")

    called = False

    def fake_parse_one(sql):
        nonlocal called
        called = True
        return sqlglot.parse_one(sql, read="sqlite")

    monkeypatch.setattr(sqlglot, "parse_one", fake_parse_one)

    sig = evalone(
        conn,
        "name from items where id=1",
        {},
        reactive=True,
        tables=tables,
        expr=expr,
    )

    assert sig.value == "z"
    assert called is False


def test_evalone_caches_derivedsignal2():
    conn = _db()
    conn.execute("INSERT INTO items(name) VALUES ('x')")
    tables = Tables(conn)
    v = Signal(1)
    sig1 = evalone(conn, "name from items where id=:v", {"v": v}, reactive=True, tables=tables)
    sig1.listeners.append(lambda _=None: None)
    sig2 = evalone(conn, "name from items where id=:v", {"v": v}, reactive=True, tables=tables)
    assert sig1 is sig2


def test_evalone_cache_key_uses_readonly_value():
    conn = _db()
    conn.execute("INSERT INTO items(name) VALUES ('x')")
    tables = Tables(conn)
    sig1 = evalone(conn, "name from items where id=:v", {"v": 1}, reactive=True, tables=tables)
    sig1.listeners.append(lambda _=None: None)
    sig2 = evalone(conn, "name from items where id=:v", {"v": 1}, reactive=True, tables=tables)
    assert sig1 is sig2

