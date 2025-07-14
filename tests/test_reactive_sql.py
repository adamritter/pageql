import sqlite3
from pathlib import Path
import sys
import sqlglot
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageql.reactive import Tables, ReactiveTable, Select, Where, Aggregate, UnionAll, Join, Order
from pageql.reactive_sql import parse_reactive, FallbackReactive
from pageql.reactive import ReadOnly


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    # Populate with a bit of data so that result comparisons are meaningful
    conn.executemany(
        "INSERT INTO items(id,name) VALUES (?,?)",
        [(1, "x"), (2, "y")],
    )
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
    assert isinstance(comp, Aggregate)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_count_expr():
    conn = _db()
    tables = Tables(conn)
    sql = "SELECT COUNT(name) FROM items"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Aggregate)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_sum_expr():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    tables = Tables(conn)
    sql = "SELECT SUM(n) FROM nums"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Aggregate)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_avg_expr():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    tables = Tables(conn)
    sql = "SELECT AVG(n) FROM nums"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Aggregate)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_union_all():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    tables = Tables(conn)
    sql = "SELECT * FROM a UNION ALL SELECT * FROM b"
    # Add sample rows so result comparison is non-trivial
    conn.execute("INSERT INTO a(id,name) VALUES (1,'a1')")
    conn.execute("INSERT INTO b(id,name) VALUES (1,'b1')")
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, UnionAll)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_join():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    tables = Tables(conn)
    sql = "SELECT a.name, b.title FROM a JOIN b ON a.id=b.a_id"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Select)
    assert isinstance(comp.parent, (Join, Select))

    events = []
    comp.listeners.append(events.append)

    ta = tables._get("a")
    tb = tables._get("b")
    ta.insert("INSERT INTO a(id,name) VALUES (1,'x')", {})
    assert events == []
    tb.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't')", {"a": 1})
    assert events == [[1, ('x', 't')]]
    tb.delete("DELETE FROM b WHERE id=1", {})
    assert events[-1] == [2, ('x', 't')]


def test_parse_join_order():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE tweets(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT)")
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    tables = Tables(conn)
    sql = "SELECT * FROM tweets JOIN users ON tweets.user_id=users.id ORDER BY tweets.id DESC"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Order)
    assert isinstance(comp.parent, (Join, Select))
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_join_alias_order():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE tweets(id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT)")
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    tables = Tables(conn)
    sql = (
        "SELECT t.id AS tid, u.username AS uname FROM tweets t "
        "JOIN users u ON t.user_id=u.id ORDER BY t.id DESC"
    )
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Order)
    assert isinstance(comp.parent, (Join, Select))
    assert_sql_equivalent(conn, sql, comp.sql)


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


def test_parse_select_subselect_fallback():
    conn = _db()
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY)")
    tables = Tables(conn)
    sql = "SELECT name FROM items WHERE id IN (SELECT id FROM nums)"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, FallbackReactive)
    assert_sql_equivalent(conn, sql, comp.sql)


def test_parse_group_by_aggregate():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, grp INTEGER, n INTEGER)")
    tables = Tables(conn)
    sql = "SELECT grp, COUNT(*), SUM(n) FROM nums GROUP BY grp"
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, Aggregate)
    assert_sql_equivalent(conn, sql, comp.sql)

    events = []
    comp.listeners.append(events.append)
    rt = tables._get("nums")
    rt.insert("INSERT INTO nums(id,grp,n) VALUES (1,1,10)", {})
    assert events[-1] == [1, (1, 1, 10)]


@pytest.mark.xfail(reason="subquery dependencies are not tracked")
def test_select_subquery_dependency():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute(
        "CREATE TABLE following(follower_id INTEGER, following_id INTEGER)"
    )
    tables = Tables(conn)
    sql = (
        "select u.id, u.username, "
        "(select count(*) from following f "
        "where f.follower_id=:current_id and f.following_id=u.id) as is_following "
        "from users u "
        "where u.username != :username "
        "order by u.username"
    )
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {"current_id": 1, "username": "alice"})

    users = tables._get("users")
    following = tables._get("following")

    users.insert("INSERT INTO users(id,username) VALUES (1,'alice')", {})
    users.insert("INSERT INTO users(id,username) VALUES (2,'bob')", {})
    assert comp.value == [(2, "bob", 0)]

    following.insert(
        "INSERT INTO following(follower_id,following_id) VALUES (1,2)",
        {},
    )
    assert comp.value == [(2, "bob", 1)]


def test_select_join_dependency():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute(
        "CREATE TABLE following(follower_id INTEGER, following_id INTEGER)"
    )
    tables = Tables(conn)
    sql = (
        "SELECT u.id, u.username, "
        "COUNT(f.following_id) AS is_following "
        "FROM users AS u "
        "LEFT JOIN following AS f "
        "ON f.follower_id = :current_id "
        "AND f.following_id = u.id "
        "WHERE u.username <> :username "
        "GROUP BY u.id, u.username "
        "ORDER BY u.username"
    )
    expr = sqlglot.parse_one(sql, read="sqlite")
    comp = parse_reactive(expr, tables, {"current_id": 1, "username": "alice"})

    users = tables._get("users")
    following = tables._get("following")

    users.insert("INSERT INTO users(id,username) VALUES (1,'alice')", {})
    users.insert("INSERT INTO users(id,username) VALUES (2,'bob')", {})
    assert comp.value == [(2, "bob", 0)]

    following.insert(
        "INSERT INTO following(follower_id,following_id) VALUES (1,2)",
        {},
    )
    assert comp.value == [(2, "bob", 1)]
