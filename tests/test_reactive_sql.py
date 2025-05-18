import sqlite3
from pathlib import Path
import types
import sys

# Ensure import path and stub watchfiles
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.reactive import Tables, ReactiveTable, Select, Where, CountAll, UnionAll
from pageql.reactive_sql import parse_reactive


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    # Populate with a bit of data so that result comparisons are meaningful
    conn.executemany("INSERT INTO items(name) VALUES (?)", [("x",), ("y",)])
    return conn


def assert_sql_equivalent(conn, original_sql, built_sql):
    """Execute *original_sql* and *built_sql* and ensure the results match."""
    res_original = list(conn.execute(original_sql).fetchall())
    res_built = list(conn.execute(built_sql).fetchall())
    assert res_original == res_built


def test_parse_select_basic():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT * FROM items"
    comp = parse_reactive(sql, tables)
    assert isinstance(comp, ReactiveTable)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_select_where():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT name FROM items WHERE name='x'"
    comp = parse_reactive(sql, tables)
    assert isinstance(comp, Select)
    assert isinstance(comp.parent, Where)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_count():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT COUNT(*) FROM items"
    comp = parse_reactive(sql, tables)
    assert isinstance(comp, CountAll)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_union_all():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    tables = Tables(conn)
    sql = "SELECT * FROM a UNION ALL SELECT * FROM b"
    # Add sample rows so result comparison is non-trivial
    conn.execute("INSERT INTO a(name) VALUES ('a1')")
    conn.execute("INSERT INTO b(name) VALUES ('b1')")
    comp = parse_reactive(sql, tables)
    assert isinstance(comp, UnionAll)
    assert_sql_equivalent(conn, sql, comp.sql)
