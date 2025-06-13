import sqlite3
from pathlib import Path
import types
import sys
import sqlglot

# Ensure import path and stub watchfiles
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.reactive import Tables, ReactiveTable, Select, Where, CountAll, UnionAll
from pageql.reactive_sql import parse_reactive, FallbackReactive
from pageql.reactive import ReadOnly


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
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, ReactiveTable)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_select_where():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT name FROM items WHERE name='x'"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Select)
    assert isinstance(comp.parent, Where)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_count():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT COUNT(*) FROM items"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
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
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, UnionAll)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_reactive_fallback_join():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    tables = Tables(conn)
    sql = "SELECT a.name, b.title FROM a JOIN b ON a.id=b.a_id"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    events = []
    comp.listeners.append(events.append)

    ta = tables._get("a")
    tb = tables._get("b")
    ta.insert("INSERT INTO a(name) VALUES ('x')", {})
    assert events == []
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    tb.insert("INSERT INTO b(a_id,title) VALUES (:a, 't')", {"a": aid})
    assert events == [[1, ('x', 't')]]
    tb.delete("DELETE FROM b WHERE id=1", {})
    assert events[-1] == [2, ('x', 't')]


def test_parse_select_with_params():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT name FROM items WHERE id = :id"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {"id": 1})
    assert isinstance(comp, Select)
    assert isinstance(comp.parent, Where)
    assert_sql_equivalent(conn, "SELECT name FROM items WHERE id = 1", comp.sql)


def test_parse_select_constant():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT 42 AS answer"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, ReadOnly)
    assert comp.value == [(42,)]


def test_parse_recursive_cte_constant():
    conn = _db()
    tables = Tables(conn)
    sql = (
        "WITH RECURSIVE numbers AS (SELECT 1 AS n UNION ALL "
        "SELECT n+1 FROM numbers WHERE n < 3) SELECT n FROM numbers"
    )
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, ReadOnly)
    assert comp.value == list(conn.execute(sql).fetchall())


def test_parse_recursive_cte_with_table_deps():
    conn = _db()
    tables = Tables(conn)
    sql = (
        "WITH RECURSIVE nums AS (SELECT 1 AS n UNION ALL SELECT n+1 FROM nums WHERE n < 2) "
        "SELECT name FROM items WHERE id IN (SELECT n FROM nums)"
    )
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = FallbackReactive(tables, sql, expr)
    assert_sql_equivalent(conn, sql, comp.sql)
    assert {d.table_name for d in comp.deps} == {"items"}
