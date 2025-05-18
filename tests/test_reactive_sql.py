import sqlite3
from pathlib import Path
import types
import sys

# Ensure import path and stub watchfiles
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.reactive import Tables, ReactiveTable, Select, Where, CountAll, UnionAll
from pageql.reactive_sql import parse_reactive, Fallback


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    return conn


def test_parse_select_basic():
    conn = _db()
    tables = Tables(conn)
    comp = parse_reactive("SELECT * FROM items", tables)
    assert isinstance(comp, ReactiveTable)


def test_parse_select_where():
    conn = _db()
    tables = Tables(conn)
    comp = parse_reactive("SELECT name FROM items WHERE name='x'", tables)
    assert isinstance(comp, Select)
    assert isinstance(comp.parent, Where)


def test_parse_count():
    conn = _db()
    tables = Tables(conn)
    comp = parse_reactive("SELECT COUNT(*) FROM items", tables)
    assert isinstance(comp, CountAll)


def test_parse_union_all():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    tables = Tables(conn)
    comp = parse_reactive("SELECT * FROM a UNION ALL SELECT * FROM b", tables)
    assert isinstance(comp, UnionAll)


def test_parse_join_fallback():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE other(id INTEGER)")
    tables = Tables(conn)
    comp = parse_reactive(
        "SELECT * FROM items JOIN other ON items.id = other.id",
        tables,
    )
    assert isinstance(comp, Fallback)


def test_fallback_events():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY)")
    tables = Tables(conn)
    comp = parse_reactive("SELECT a.id, b.id FROM a JOIN b ON a.id=b.id", tables)
    events = []
    comp.listeners.append(events.append)

    tables.executeone("INSERT INTO a(id) VALUES (1)", {})
    tables.executeone("INSERT INTO b(id) VALUES (1)", {})
    assert events[-1] == [1, (1, 1)]

    tables.executeone("DELETE FROM a WHERE id=1", {})
    assert events[-1] == [2, (1, 1)]
