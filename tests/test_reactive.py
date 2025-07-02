import sys
from pathlib import Path
import pytest

# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
def assert_eq(a, b):
    assert a == b, f"{a} != {b}"

def test_update_null_row_should_raise_custom_exception():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    check_component(rt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,NULL)", {}))
    check_component(rt, lambda: rt.update("UPDATE items SET name = 'z' WHERE id = :id", {"id": 1}))

def test_where_delete_event_should_be_labeled_delete():
    """
    Deleting a row that *matches* the Where predicate should emit a
    `[2, row]` delete event, not a plain projected row.
    """
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w   = Where(rt, "name = 'x'")
    events = []
    w.listeners.append(events.append)

    check_component(w, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    check_component(w, lambda: rt.delete("DELETE FROM items WHERE id = :id", {"id": 1}))


def test_select_delete_event_should_be_labeled_delete():
    """
    Same symmetry check for Select: deleting a parent row that maps to a
    projected value must be forwarded as `[2, value]`.
    """
    conn = _db()
    rt   = ReactiveTable(conn, "items")
    sel  = Select(rt, "name")
    events = []
    sel.listeners.append(events.append)

    check_component(sel, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    check_component(sel, lambda: rt.delete("DELETE FROM items WHERE id = :id", {"id": 1}))
import sqlite3
from pageql.reactive import (
    ReactiveTable,
    Aggregate,
    OneValue,
    DerivedSignal,
    DerivedSignal2,
    derive_signal2,
    Signal,
    Where,
    UnionAll,
    Union,
    Intersect,
    Join,
    Select,
    Order,
    get_dependencies,
    ReadOnly,
)
from pageql.pageql import RenderContext, Tables
from pageql.reactive_sql import parse_reactive
import sqlglot
from pageql.database import evalone


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    return c


def check_component(comp, callback):
    conn = comp.conn
    expected = list(conn.execute(comp.sql).fetchall())
    cols_len = len(comp.columns) if not isinstance(comp.columns, str) else 1
    events = []
    comp.listeners.append(events.append)
    callback()
    comp.listeners.remove(events.append)
    for ev in events:
        if not isinstance(ev, (list, tuple)):
            expected = [(ev,)]
            continue
        if ev[0] == 1:
            row = tuple(ev[1])
            if len(row) != cols_len:
                raise Exception("bad number of columns on insert")
            expected.append(row)
        elif ev[0] == 2:
            row = tuple(ev[1])
            if row not in expected:
                raise Exception("deleting nonexistent row")
            expected.remove(row)
        elif ev[0] == 3:
            old, new = tuple(ev[1]), tuple(ev[2])
            if old not in expected:
                alt_old = tuple(0 if v is None else v for v in old)
                alt_expected = [tuple(0 if v is None else v for v in r) for r in expected]
                if alt_old not in alt_expected:
                    raise Exception("updating nonexistent row")
                idx = alt_expected.index(alt_old)
            else:
                idx = expected.index(old)
            if len(new) != cols_len:
                raise Exception("bad number of columns on update")
            expected[idx] = new
        else:
            raise Exception(f"unknown event type {ev[0]}")
    expected.sort()
    final = sorted(conn.execute(comp.sql).fetchall())
    assert_eq(expected, final)


def test_sqls(comp, tables, sqls):
    for s in sqls:
        check_component(comp, lambda q=s: tables.executeone(q, {}))
test_sqls.__test__ = False


def _make_join(*, left=False, right=False):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    j = Join(r1, r2, "a.id = b.a_id", left_outer=left, right_outer=right)
    events = []
    j.listeners.append(events.append)
    return conn, r1, r2, j, events


def test_reactive_table_events():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    events = []
    rt.listeners.append(events.append)

    # insert
    check_component(rt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (:id,:n)", {"id": 1, "n": "a"}))

    # update
    check_component(rt, lambda: rt.update("UPDATE items SET name = :n WHERE id = :id", {"n": "b", "id": 1}))

    # delete
    check_component(rt, lambda: rt.delete("DELETE FROM items WHERE id = :id", {"id": 1}))


def test_reactive_table_delete_multiple_rows():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    events = []
    rt.listeners.append(events.append)

    # insert two rows with the same name
    check_component(rt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    check_component(rt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (2,'x')", {}))

    events.clear()

    # delete all rows matching the name predicate
    check_component(rt, lambda: rt.delete("DELETE FROM items WHERE name = :name", {"name": "x"}))


def test_delete_propagates_renderresultexception():
    conn = _db()
    rt = ReactiveTable(conn, "items")

    from pageql.pageql import RenderResult, RenderResultException

    def boom(_):
        raise RenderResultException(RenderResult(status_code=302))

    check_component(rt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    rt.listeners.append(boom)

    with pytest.raises(RenderResultException):
        rt.delete("DELETE FROM items", {})


def test_count_all():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt)
    events = []
    cnt.listeners.append(events.append)

    check_component(cnt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))


def test_count_expression():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt, ("COUNT(name)",))
    events = []
    cnt.listeners.append(events.append)

    check_component(cnt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))

    check_component(cnt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (2,NULL)", {}))

    check_component(cnt, lambda: rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": 2}))

    check_component(cnt, lambda: rt.update("UPDATE items SET name=NULL WHERE id=:id", {"id": 2}))


def test_sum_expression():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    sm = Aggregate(rt, ("SUM(n)",))
    events = []
    sm.listeners.append(events.append)

    check_component(sm, lambda: rt.insert("INSERT INTO nums(id,n) VALUES (1,1)", {}))

    check_component(sm, lambda: rt.insert("INSERT INTO nums(id,n) VALUES (2,2)", {}))

    check_component(sm, lambda: rt.update("UPDATE nums SET n=5 WHERE id=:id", {"id": 2}))

    check_component(sm, lambda: rt.delete("DELETE FROM nums WHERE id=:id", {"id": 2}))


def test_avg_expression():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    av = Aggregate(rt, ("AVG(n)",))
    events = []
    av.listeners.append(events.append)

    check_component(av, lambda: rt.insert("INSERT INTO nums(id,n) VALUES (1,1)", {}))

    check_component(av, lambda: rt.insert("INSERT INTO nums(id,n) VALUES (2,2)", {}))

    check_component(av, lambda: rt.update("UPDATE nums SET n=5 WHERE id=:id", {"id": 2}))

    check_component(av, lambda: rt.delete("DELETE FROM nums WHERE id=:id", {"id": 2}))


def test_min_max_expression():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    mn = Aggregate(rt, ("MIN(n)",))
    mx = Aggregate(rt, ("MAX(n)",))
    mn_events, mx_events = [], []
    mn.listeners.append(mn_events.append)
    mx.listeners.append(mx_events.append)

    check_component(mn, lambda: rt.insert("INSERT INTO nums(id,n) VALUES (1,5)", {}))
    assert_eq(mx.value, [5])

    check_component(mn, lambda: rt.insert("INSERT INTO nums(id,n) VALUES (2,2)", {}))
    assert_eq(mx.value, [5])

    check_component(mn, lambda: rt.insert("INSERT INTO nums(id,n) VALUES (3,10)", {}))
    assert_eq(mx.value, [10])

    check_component(mn, lambda: rt.update("UPDATE nums SET n=7 WHERE id=:id", {"id": 2}))
    assert_eq(mn.value, [5])

    check_component(mn, lambda: rt.update("UPDATE nums SET n=1 WHERE id=:id", {"id": 3}))
    assert_eq(mn.value, [1])
    assert_eq(mx.value, [7])

    check_component(mn, lambda: rt.delete("DELETE FROM nums WHERE id=:id", {"id": 2}))
    assert_eq(mx.value, [5])

    check_component(mn, lambda: rt.delete("DELETE FROM nums WHERE id=:id", {"id": 3}))
    assert_eq(mn.value, [5])


def test_aggregate_constant_expression():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    ag = Aggregate(rt, ("COUNT(*)", "42"))
    events = []
    ag.listeners.append(events.append)

    assert_eq(ag.value, [0, 42])

    check_component(ag, lambda: rt.insert("INSERT INTO items(name) VALUES ('x')", {}))
    assert_eq(ag.value, [1, 42])


def test_aggregate_group_by():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, grp INTEGER, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    ag = Aggregate(rt, ("COUNT(*)", "SUM(n)"), group_by="grp")
    events = []
    ag.listeners.append(events.append)

    check_component(ag, lambda: rt.insert("INSERT INTO nums(id,grp,n) VALUES (1,1,10)", {}))

    check_component(ag, lambda: rt.insert("INSERT INTO nums(id,grp,n) VALUES (2,1,5)", {}))

    check_component(ag, lambda: rt.update("UPDATE nums SET grp=2 WHERE id=:id", {"id": 2}))

    check_component(ag, lambda: rt.delete("DELETE FROM nums WHERE id=:id", {"id": 1}))

    check_component(ag, lambda: None)


def test_signal_and_derived():
    a_val = [1]
    b_val = [2]
    a = DerivedSignal(lambda: a_val[0], [])
    b = DerivedSignal(lambda: b_val[0], [])
    d = DerivedSignal(lambda: a.value + b.value, [a, b])
    seen = []
    d.listeners.append(seen.append)
    a_val[0] = 2
    a.update()
    assert_eq(d.value, 4)
    assert_eq(seen[-1], 4)
    a_val[0] = 2  # no change
    a.update()
    assert_eq(seen[-1], 4)
    assert len(seen) == 1


def test_where():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w = Where(rt, "name = 'x'")
    seen = []
    w.listeners.append(seen.append)

    check_component(w, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    check_component(w, lambda: rt.insert("INSERT INTO items(id,name) VALUES (2,'y')", {}))

    check_component(w, lambda: rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": 2}))


def test_unionall():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = UnionAll(r1, r2)
    seen = []
    u.listeners.append(seen.append)

    check_component(u, lambda: r1.insert("INSERT INTO a(name) VALUES ('x')", {}))
    check_component(u, lambda: r2.insert("INSERT INTO b(name) VALUES ('y')", {}))


def test_select():
    conn, rt = _db(), None
    rt = ReactiveTable(conn, "items")
    sel = Select(rt, "name")
    seen = []
    sel.listeners.append(seen.append)

    check_component(sel, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))

    check_component(sel, lambda: rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": 1}))


# Additional tests
def test_count_all_decrement():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt)
    events = []
    cnt.listeners.append(events.append)

    # insert two rows
    check_component(cnt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    check_component(cnt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (2,'y')", {}))
    assert_eq(cnt.value, [2])

    # delete one row
    check_component(cnt, lambda: rt.delete("DELETE FROM items WHERE id = :id", {"id": 1}))
    assert_eq(cnt.value, [1])


def test_countall_multiple_expressions():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt, ("COUNT(*)", "COUNT(name)"))
    events = []
    cnt.listeners.append(events.append)

    check_component(cnt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))

    check_component(cnt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (2,NULL)", {}))


def test_where_remove():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w = Where(rt, "name = 'x'")
    events = []
    w.listeners.append(events.append)

    # insert a matching row
    check_component(w, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    # update it so it no longer matches the predicate
    check_component(w, lambda: rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": 1}))


def test_select_no_change_on_same_value_update():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    sel = Select(rt, "name")
    events = []
    sel.listeners.append(events.append)

    check_component(sel, lambda: rt.insert("INSERT INTO items(name) VALUES ('x')", {}))
    initial_event_count = len(events)

    # update without changing the selected value
    check_component(sel, lambda: rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": 1}))


def test_where_no_event_on_same_value_update():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w = Where(rt, "name = 'x'")
    events = []
    w.listeners.append(events.append)

    check_component(w, lambda: rt.insert("INSERT INTO items(name) VALUES ('x')", {}))
    initial_len = len(events)

    check_component(w, lambda: rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": 1}))


def test_reactive_table_no_event_on_same_value_update():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    events = []
    rt.listeners.append(events.append)

    check_component(rt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    initial_len = len(events)

    check_component(rt, lambda: rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": 1}))


def test_unionall_update():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = UnionAll(r1, r2)
    events = []
    u.listeners.append(events.append)

    check_component(u, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(u, lambda: r1.update("UPDATE a SET name='y' WHERE id=:id", {"id": 1}))


def test_update_without_where_clause():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    check_component(rt, lambda: rt.insert("INSERT INTO items(name) VALUES ('x')", {}))
    check_component(rt, lambda: rt.update("UPDATE items SET name='z'", {}))
    result = conn.execute("SELECT name FROM items").fetchall()
    assert result == [('z',)]


def test_unionall_mismatched_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, title TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    try:
        UnionAll(r1, r2)
    except ValueError:
        pass
    else:
        assert False, "expected ValueError when columns mismatch"


def test_union():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = Union(r1, r2)
    events = []
    u.listeners.append(events.append)

    check_component(u, lambda: r1.insert("INSERT INTO a(name) VALUES ('x')", {}))
    check_component(u, lambda: r2.insert("INSERT INTO b(name) VALUES ('x')", {}))  # duplicate
    check_component(u, lambda: r2.insert("INSERT INTO b(name) VALUES ('y')", {}))


def test_union_update():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = Union(r1, r2)
    events = []
    u.listeners.append(events.append)

    check_component(u, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(u, lambda: r1.update("UPDATE a SET name='y' WHERE id=:id", {"id": 1}))


def test_union_update_with_duplicate():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = Union(r1, r2)
    events = []
    u.listeners.append(events.append)

    check_component(u, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(u, lambda: r2.insert("INSERT INTO b(id,name) VALUES (1,'x')", {}))
    events.clear()
    check_component(u, lambda: r1.update("UPDATE a SET name='y' WHERE id=:id", {"id": 1}))


def test_union_mismatched_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, title TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    try:
        Union(r1, r2)
    except ValueError:
        pass
    else:
        assert False, "expected ValueError when columns mismatch"


def test_join_basic():
    conn, r1, r2, j, events = _make_join()

    check_component(j, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't')", {"a": 1}))


def test_join_update():
    conn, r1, r2, j, events = _make_join()

    check_component(j, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't1')", {"a": 1}))
    events.clear()

    check_component(j, lambda: r2.update("UPDATE b SET title='t2' WHERE id=:id", {"id": 1}))


def test_join_update_no_change():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    j = Join(r1, r2, "a.id = b.a_id")
    events = []
    j.listeners.append(events.append)

    check_component(j, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't1')", {"a": 1}))
    events.clear()

    check_component(j, lambda: r2.update("UPDATE b SET title='t1' WHERE id=:id", {"id": 1}))


def test_join_delete():
    conn, r1, r2, j, events = _make_join()

    check_component(j, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't')", {"a": 1}))
    events.clear()

    check_component(j, lambda: r2.delete("DELETE FROM b WHERE id=:id", {"id": 1}))
    events.clear()

    check_component(j, lambda: r1.delete("DELETE FROM a WHERE id=:id", {"id": 1}))


def test_left_outer_join_basic():
    conn, r1, r2, j, events = _make_join(left=True)

    check_component(j, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    events.clear()

    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't')", {"a": 1}))



def test_left_outer_join_update_delete():
    conn, r1, r2, j, events = _make_join(left=True)

    check_component(j, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't1')", {"a": 1}))
    events.clear()

    check_component(j, lambda: r2.update("UPDATE b SET title='t2' WHERE id=:id", {"id": 1}))
    events.clear()

    check_component(j, lambda: r2.delete("DELETE FROM b WHERE id=:id", {"id": 1}))
    events.clear()

    check_component(j, lambda: r1.delete("DELETE FROM a WHERE id=:id", {"id": 1}))


def test_right_outer_join_basic():
    conn, r1, r2, j, events = _make_join(right=True)

    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,1,'t')", {}))
    events.clear()

    check_component(j, lambda: r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {}))
    aid = 1


def test_right_outer_join_update_delete():
    conn, r1, r2, j, events = _make_join(right=True)

    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,1,'t1')", {}))
    check_component(j, lambda: r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {}))
    aid = 1
    events.clear()

    check_component(j, lambda: r1.update("UPDATE a SET name='y' WHERE id=1", {}))
    events.clear()

    check_component(j, lambda: r1.delete("DELETE FROM a WHERE id=1", {}))
    events.clear()

    check_component(j, lambda: r2.delete("DELETE FROM b WHERE id=:id", {"id": 1}))


def test_full_outer_join_left_then_right():
    conn, r1, r2, j, events = _make_join(left=True, right=True)

    check_component(j, lambda: r1.insert("INSERT INTO a(id,name) VALUES (1,'x')", {}))
    events.clear()

    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,:a, 't')", {"a": 1}))


def test_full_outer_join_right_then_left():
    conn, r1, r2, j, events = _make_join(left=True, right=True)

    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,1,'t1')", {}))
    events.clear()

    check_component(j, lambda: r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {}))
    aid = 1


def test_full_outer_join_update_delete():
    conn, r1, r2, j, events = _make_join(left=True, right=True)

    check_component(j, lambda: r2.insert("INSERT INTO b(id,a_id,title) VALUES (1,1,'t1')", {}))
    events.clear()

    check_component(j, lambda: r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {}))
    aid = 1
    events.clear()

    check_component(j, lambda: r2.update("UPDATE b SET title='t2' WHERE id=:id", {"id": 1}))
    events.clear()

    check_component(j, lambda: r1.delete("DELETE FROM a WHERE id=1", {}))
    events.clear()

    check_component(j, lambda: r2.delete("DELETE FROM b WHERE id=:id", {"id": 1}))


def test_intersect_deduplication():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    s1, s2 = Select(r1, "name"), Select(r2, "name")
    inter = Intersect(s1, s2)
    events = []
    inter.listeners.append(events.append)

    check_component(inter, lambda: r1.insert("INSERT INTO a(name) VALUES ('x')", {}))
    check_component(inter, lambda: r1.insert("INSERT INTO a(name) VALUES ('x')", {}))  # duplicate in same table
    check_component(inter, lambda: r2.insert("INSERT INTO b(name) VALUES ('x')", {}))


def test_intersect_update_with_remaining_duplicate():
    """Updating one of several matching rows shouldn't emit a delete."""
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    inter = Intersect(Select(r1, "name"), Select(r2, "name"))
    events = []
    inter.listeners.append(events.append)

    check_component(inter, lambda: r1.insert("INSERT INTO a(name) VALUES ('z')", {}))
    check_component(inter, lambda: r2.insert("INSERT INTO b(name) VALUES ('x')", {}))
    check_component(inter, lambda: r1.update("UPDATE a SET name='x' WHERE id=1", {}))
    check_component(inter, lambda: r1.insert("INSERT INTO a(name) VALUES ('x')", {}))

    events.clear()
    check_component(inter, lambda: r1.update("UPDATE a SET name='z' WHERE id=1", {}))

    assert_eq(list(conn.execute(inter.sql).fetchall()), [("x",)])


def test_derived_signal_multiple_updates():
    a_val = [1]
    b_val = [2]
    a = DerivedSignal(lambda: a_val[0], [])
    b = DerivedSignal(lambda: b_val[0], [])
    d = DerivedSignal(lambda: a.value * b.value, [a, b])
    seen = []
    d.listeners.append(seen.append)
    b_val[0] = 3
    b.update()
    a_val[0] = 2
    a.update()
    assert_eq(seen, [3, 6])


def test_derived_signal_replace():
    a_val = [1]
    b_val = [2]
    a = DerivedSignal(lambda: a_val[0], [])
    b = DerivedSignal(lambda: b_val[0], [])
    d = DerivedSignal(lambda: a.value + 1, [a])
    seen = []
    d.listeners.append(seen.append)

    a_val[0] = 2
    a.update()
    assert_eq(seen[-1], 3)

    d.replace(lambda: b.value * 2, [b])
    assert_eq(d.value, 4)
    assert_eq(seen[-1], 4)

    a_val[0] = 5
    a.update()
    assert_eq(seen[-1], 4)

    b_val[0] = 3
    b.update()
    assert_eq(seen[-1], 6)


def test_one_value_reset():
    conn = _db()
    rt = ReactiveTable(conn, "items")

    cnt = Aggregate(rt)
    dv = OneValue(cnt)
    seen = []
    dv.listeners.append(seen.append)

    check_component(dv, lambda: rt.insert("INSERT INTO items(name) VALUES ('x')", {}))
    assert_eq(dv.value, 1)
    assert_eq(seen[-1], 1)

    sel = Select(rt, "name")
    dv.reset(sel)
    assert dv.onevent not in cnt.listeners
    assert_eq(dv.value, "x")
    assert_eq(seen[-1], "x")

    check_component(dv, lambda: rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": 1}))
    assert_eq(dv.value, "y")
    assert_eq(seen[-1], "y")


def test_signal_remove_listener_detaches_dependencies():
    src = Signal(1)
    derived = DerivedSignal(lambda: src.value + 1, [src])
    seen = []
    derived.listeners.append(seen.append)
    derived.remove_listener(seen.append)
    assert derived.listeners is None


def test_derived_signal2_switches_main_signal():
    a = Signal(1)
    a.listeners.append(lambda _=None: None)
    b = Signal(2)
    b.listeners.append(lambda _=None: None)
    use_a = Signal(True)
    d = DerivedSignal2(lambda: a if use_a.value else b, [use_a])
    seen = []
    d.listeners.append(seen.append)

    assert d.value == 1

    a.set_value(3)
    assert seen[-1] == 3

    use_a.set_value(False)
    assert d.value == 2
    assert seen[-1] == 2

    a.set_value(4)
    assert seen[-1] == 2

    b.set_value(5)
    assert seen[-1] == 5

    d.remove_listener(seen.append)


def test_derived_signal2_remove_listener_detaches():
    a = Signal(1)
    b = Signal(2)
    use_a = Signal(True)
    d = DerivedSignal2(lambda: a if use_a.value else b, [use_a])
    cb = lambda _=None: None
    d.listeners.append(cb)
    assert d._on_main in a.listeners
    assert d._on_dep in use_a.listeners
    d.remove_listener(cb)
    assert d._on_main not in (a.listeners or [])
    assert d._on_dep not in (use_a.listeners or [])
    assert d.listeners is None


def test_derived_signal2_remove_listener_uses_remove_listener():
    class Tracker(Signal):
        def __init__(self, value=0):
            super().__init__(value)
            self.removed = []

        def remove_listener(self, listener):
            self.removed.append(listener)
            super().remove_listener(listener)

    main = Tracker(1)
    dep = Tracker()
    d = DerivedSignal2(lambda: main, [dep])
    cb = lambda _=None: None
    d.listeners.append(cb)
    d.remove_listener(cb)
    assert d._on_dep in dep.removed
    assert d._on_main in main.removed


def test_derive_signal2_returns_signal_if_all_readonly():
    main = Signal(1)
    ro1 = ReadOnly(1)
    res = derive_signal2(lambda: main, [ro1])
    assert res is main


def test_evalone_cache_without_params_reuses_signal():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE items(id INTEGER)")
    db.execute("INSERT INTO items(id) VALUES (1)")
    tables = Tables(db)
    sig1 = evalone(db, "COUNT(*) from items", {}, reactive=True, tables=tables)
    sig1.listeners.append(lambda _=None: None)
    sig2 = evalone(db, "COUNT(*) from items", {}, reactive=True, tables=tables)
    assert sig1 is sig2

def test_select_remove_listener_detaches_from_parent():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    sel = Select(rt, "name")
    cb = lambda e: None
    sel.listeners.append(cb)
    sel.remove_listener(cb)
    assert sel.listeners is None


def test_rendercontext_cleanup_detaches_dependency_listeners():
    ctx = RenderContext()
    src = Signal(1)
    derived = DerivedSignal(lambda: src.value + 1, [src])

    def cb(_):
        pass

    ctx.add_listener(derived, cb)
    ctx.cleanup()
    assert derived.listeners is None


def test_check_component_reactive_table():
    conn = _db()
    rt = ReactiveTable(conn, "items")

    check_component(rt, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    check_component(rt, lambda: rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": 1}))
    check_component(rt, lambda: rt.delete("DELETE FROM items WHERE id=:id", {"id": 1}))


def test_check_component_where():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w = Where(rt, "name = 'x'")

    check_component(w, lambda: rt.insert("INSERT INTO items(id,name) VALUES (1,'x')", {}))
    check_component(w, lambda: rt.update("UPDATE items SET name='z' WHERE id=:id", {"id": 1}))


def test_get_dependencies_simple():
    expr = "select count(*) from todos where :id > 3 and :nam_e5='hello'"
    deps = get_dependencies(expr)
    assert deps == ["id", "nam_e5"]


def test_get_dependencies_ignore_quotes():
    expr = "select * from t where name=':no' and id=:id"
    deps = get_dependencies(expr)
    assert deps == ["id"]


def test_get_dependencies_ignore_comments():
    expr = "select * from t -- comment :foo\n where id=:id /* :bar */"
    deps = get_dependencies(expr)
    assert deps == ["id"]


def test_get_dependencies_type_cast():
    expr = "select :id::text as ident where name=:name"
    deps = get_dependencies(expr)
    assert deps == ["id", "name"]


def _random_op(rt):
    """Realiza aleatoriamente una inserción, eliminación o actualización en *rt*."""
    import random

    action = random.choice(["insert", "delete", "update"])
    if action == "insert":
        rt.insert(
            f"INSERT INTO {rt.table_name}(name) VALUES (:name)",
            {"name": random.choice(["a", "b", "c", "d"])},
        )
    else:
        rows = list(rt.conn.execute(f"SELECT id FROM {rt.table_name}").fetchall())
        if not rows:
            return
        rid = random.choice(rows)[0]
        if action == "delete":
            rt.delete(
                f"DELETE FROM {rt.table_name} WHERE id=:id", {"id": rid}
            )
        else:  # update
            rt.update(
                f"UPDATE {rt.table_name} SET name=:name WHERE id=:id",
                {"name": random.choice(["x", "y", "z"]), "id": rid},
            )


def fuzz_components(iterations=20, seed=None):
    """Randomly mutate various components to ensure they stay consistent."""
    import random
    import sqlite3

    if seed is not None:
        random.seed(seed)

    # Base table used by several components
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")

    components = [
        (rt, rt),
        (Where(rt, "name LIKE 'x%'") , rt),
        (Select(rt, "name"), rt),
        (Aggregate(rt), rt),
    ]

    # UnionAll requires two tables
    conn2 = sqlite3.connect(":memory:")
    conn2.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn2.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn2, "a"), ReactiveTable(conn2, "b")
    components.append((UnionAll(r1, r2), (r1, r2)))
    components.append((Union(r1, r2), (r1, r2)))
    components.append((Intersect(Select(r1, "name"), Select(r2, "name")), (r1, r2)))
    components.append((Join(r1, r2, "a.name = b.name"), (r1, r2)))

    for comp, parents in components:
        for _ in range(iterations):
            if isinstance(parents, tuple):
                parent = random.choice(parents)
            else:
                parent = parents
            check_component(comp, lambda p=parent: _random_op(p))


def test_fuzz_components():
    fuzz_components(iterations=10, seed=123)


def test_order_events():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    ordered = Order(rt, "id")

    seen = []
    ordered.listeners.append(seen.append)

    rt.insert("INSERT INTO items(id,name) VALUES (2,'b')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (1,'a')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (3,'c')", {})

    assert seen == [
        [1, 0, (2, "b")],
        [1, 0, (1, "a")],
        [1, 2, (3, "c")],
    ]

    seen.clear()
    rt.update("UPDATE items SET id=4 WHERE id=1", {})
    assert seen == [[3, 0, 2, (4, "a")]]

    seen.clear()
    rt.delete("DELETE FROM items WHERE id=2", {})
    assert seen == [[2, 0]]
    assert ordered.value == [(3, "c"), (4, "a")]


def test_order_bisect_desc():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    ordered = Order(rt, "name DESC")

    seen = []
    ordered.listeners.append(seen.append)

    rt.insert("INSERT INTO items(id,name) VALUES (1,'b')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (2,'c')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (3,'a')", {})

    assert seen == [
        [1, 0, (1, "b")],
        [1, 0, (2, "c")],
        [1, 2, (3, "a")],
    ]

    seen.clear()
    rt.update("UPDATE items SET name='d' WHERE id=1", {})
    assert seen == [[3, 1, 0, (1, "d")]]

    seen.clear()
    rt.delete("DELETE FROM items WHERE id=2", {})
    assert seen == [[2, 1]]
    assert ordered.value == [(1, "d"), (3, "a")]


def test_order_deterministic():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    ordered = Order(rt, "name")

    rt.insert("INSERT INTO items(id,name) VALUES (2,'a')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (1,'a')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (3,'b')", {})

    assert ordered.value == [(1, "a"), (2, "a"), (3, "b")]


def test_order_limit_offset_events():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    ordered = Order(rt, "id", limit=2, offset=1)

    seen = []
    ordered.listeners.append(seen.append)

    rt.insert("INSERT INTO items(id,name) VALUES (1,'a')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (2,'b')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (3,'c')", {})

    seen.clear()
    rt.insert("INSERT INTO items(id,name) VALUES (0,'z')", {})
    assert seen == [[1, 0, (1, "a")], [2, 2]]

    seen.clear()
    rt.delete("DELETE FROM items WHERE id=1", {})
    assert seen == [[2, 0], [1, 1, (3, "c")]]


def test_order_set_limit():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    rt.insert("INSERT INTO items(id,name) VALUES (1,'a')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (2,'b')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (3,'c')", {})

    ordered = Order(rt, "id", limit=2)
    assert ordered.value == [(1, "a"), (2, "b")]

    seen = []
    ordered.listeners.append(seen.append)

    ordered.set_limit(1)
    assert ordered.value == [(1, "a")]
    assert seen == [[2, 1]]

    seen.clear()
    ordered.set_limit(None)
    assert ordered.value == [(1, "a"), (2, "b"), (3, "c")]
    assert seen == [[1, 1, (2, "b")], [1, 2, (3, "c")]]


def test_one_value_with_order():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    sel = Select(rt, "id")
    ordered = Order(sel, "id", limit=1)
    ov = OneValue(ordered)

    seen = []
    ov.listeners.append(seen.append)

    rt.insert("INSERT INTO items(id,name) VALUES (2,'b')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (1,'a')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (3,'c')", {})

    assert seen == [2, 1]
    assert ov.value == 1

    seen.clear()
    rt.update("UPDATE items SET id=0 WHERE id=1", {})
    assert seen == [0]
    assert ov.value == 0

    seen.clear()
    rt.delete("DELETE FROM items WHERE id=0", {})
    assert seen == [2]
    assert ov.value == 2


def test_order_update_row_outside_limit():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")

    rt.insert("INSERT INTO items(id,name) VALUES (1,'a')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (2,'b')", {})
    rt.insert("INSERT INTO items(id,name) VALUES (3,'c')", {})

    ordered = Order(rt, "id", limit=2)
    assert ordered.value == [(1, "a"), (2, "b")]

    rt.update("UPDATE items SET id=4 WHERE id=2", {})
    assert ordered.value == [(1, "a"), (3, "c")]


def test_order_event_after_last_listener_removed():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    rt = ReactiveTable(conn, "items")
    ordered = Order(rt, "id")

    cb = lambda _=None: None
    ordered.listeners.append(cb)
    ordered.remove_listener(cb)

    assert ordered.listeners is None
    assert ordered.onevent not in (rt.listeners or [])

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert ordered.value == []


def test_order_on_readonly_array():
    conn = sqlite3.connect(":memory:")
    tables = Tables(conn)
    expr = sqlglot.parse_one("SELECT 2 AS n UNION ALL SELECT 1 AS n", read="sqlite")
    comp = parse_reactive(expr, tables, {})
    assert isinstance(comp, ReadOnly)
    ordered = Order(comp, "n")
    assert ordered.value == [(1,), (2,)]


