import sys
from pathlib import Path
import types
import pytest

# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
def assert_eq(a, b):
    assert a == b, f"{a} != {b}"

def test_update_null_row_should_raise_custom_exception():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    rt.insert("INSERT INTO items(name) VALUES (NULL)", {})  # row with NULL
    rid = conn.execute("SELECT id FROM items WHERE name IS NULL").fetchone()[0]
    rt.update("UPDATE items SET name = 'z' WHERE id = :id", {"id": rid})

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

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rid = conn.execute("SELECT id FROM items WHERE name = 'x'").fetchone()[0]
    rt.delete("DELETE FROM items WHERE id = :id", {"id": rid})

    assert events[-1][0] == 2, (
        "Where should emit a delete event label 2, but got %r" % (events[-1],)
    )


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

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rid = conn.execute("SELECT id FROM items WHERE name = 'x'").fetchone()[0]
    rt.delete("DELETE FROM items WHERE id = :id", {"id": rid})

    assert_eq(events[-1], [2, ('x',)])
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
    get_dependencies,
    ReadOnly,
)
from pageql.pageql import RenderContext, Tables
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
                raise Exception("updating nonexistent row")
            if len(new) != cols_len:
                raise Exception("bad number of columns on update")
            idx = expected.index(old)
            expected[idx] = new
        else:
            raise Exception(f"unknown event type {ev[0]}")
    expected.sort()
    final = sorted(conn.execute(comp.sql).fetchall())
    assert_eq(expected, final)


def _make_join(*, left=False, right=False):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    j = Join(r1, r2, "a.id = b.a_id", left_outer=left, right_outer=right)
    events = []
    j.listeners.append(events.append)
    return conn, r1, r2, events


def test_reactive_table_events():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    events = []
    rt.listeners.append(events.append)

    # insert
    rt.insert("INSERT INTO items(name) VALUES (:n)", {"n": "a"})
    assert_eq(events[-1], [1, (1, 'a')])
    rid = events[-1][1][0]

    # update
    rt.update("UPDATE items SET name = :n WHERE id = :id", {"n": "b", "id": rid})
    assert_eq(events[-1], [3, (1, 'a'), (1, 'b')])

    # delete
    rt.delete("DELETE FROM items WHERE id = :id", {"id": rid})
    assert_eq(events[-1], [2, (1, 'b')])


def test_reactive_table_delete_multiple_rows():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    events = []
    rt.listeners.append(events.append)

    # insert two rows with the same name
    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rt.insert("INSERT INTO items(name) VALUES ('x')", {})

    ids = [r[0] for r in conn.execute("SELECT id FROM items WHERE name='x'").fetchall()]
    events.clear()

    # delete all rows matching the name predicate
    rt.delete("DELETE FROM items WHERE name = :name", {"name": "x"})

    assert_eq(events, [[2, (ids[0], 'x')], [2, (ids[1], 'x')]])


def test_delete_propagates_renderresultexception():
    conn = _db()
    rt = ReactiveTable(conn, "items")

    from pageql.pageql import RenderResult, RenderResultException

    def boom(_):
        raise RenderResultException(RenderResult(status_code=302))

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rt.listeners.append(boom)

    with pytest.raises(RenderResultException):
        rt.delete("DELETE FROM items", {})


def test_count_all():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt)
    events = []
    cnt.listeners.append(events.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert_eq(cnt.value, [1])
    assert_eq(events[-1], [3, [0], [1]])


def test_count_expression():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt, ("COUNT(name)",))
    events = []
    cnt.listeners.append(events.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert_eq(cnt.value, [1])
    assert_eq(events[-1], [3, [0], [1]])

    rt.insert("INSERT INTO items(name) VALUES (NULL)", {})
    assert_eq(cnt.value, [1])

    rid = conn.execute("SELECT id FROM items WHERE name IS NULL").fetchone()[0]
    rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": rid})
    assert_eq(cnt.value, [2])
    assert_eq(events[-1], [3, [1], [2]])

    rt.update("UPDATE items SET name=NULL WHERE id=:id", {"id": rid})
    assert_eq(cnt.value, [1])
    assert_eq(events[-1], [3, [2], [1]])


def test_sum_expression():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    sm = Aggregate(rt, ("SUM(n)",))
    events = []
    sm.listeners.append(events.append)

    rt.insert("INSERT INTO nums(n) VALUES (1)", {})
    assert_eq(sm.value, [1])
    assert_eq(events[-1], [3, [0], [1]])

    rt.insert("INSERT INTO nums(n) VALUES (2)", {})
    assert_eq(sm.value, [3])
    assert_eq(events[-1], [3, [1], [3]])

    rid = conn.execute("SELECT id FROM nums WHERE n=2").fetchone()[0]
    rt.update("UPDATE nums SET n=5 WHERE id=:id", {"id": rid})
    assert_eq(sm.value, [6])
    assert_eq(events[-1], [3, [3], [6]])

    rt.delete("DELETE FROM nums WHERE id=:id", {"id": rid})
    assert_eq(sm.value, [1])
    assert_eq(events[-1], [3, [6], [1]])


def test_avg_expression():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    av = Aggregate(rt, ("AVG(n)",))
    events = []
    av.listeners.append(events.append)

    rt.insert("INSERT INTO nums(n) VALUES (1)", {})
    assert_eq(av.value, [1])
    assert_eq(events[-1], [3, [0], [1]])

    rt.insert("INSERT INTO nums(n) VALUES (2)", {})
    assert_eq(av.value, [1.5])
    assert_eq(events[-1], [3, [1], [1.5]])

    rid = conn.execute("SELECT id FROM nums WHERE n=2").fetchone()[0]
    rt.update("UPDATE nums SET n=5 WHERE id=:id", {"id": rid})
    assert_eq(av.value, [3])
    assert_eq(events[-1], [3, [1.5], [3]])

    rt.delete("DELETE FROM nums WHERE id=:id", {"id": rid})
    assert_eq(av.value, [1])
    assert_eq(events[-1], [3, [3], [1]])


def test_min_max_expression():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    mn = Aggregate(rt, ("MIN(n)",))
    mx = Aggregate(rt, ("MAX(n)",))
    mn_events, mx_events = [], []
    mn.listeners.append(mn_events.append)
    mx.listeners.append(mx_events.append)

    rt.insert("INSERT INTO nums(n) VALUES (5)", {})
    assert_eq(mn.value, [5])
    assert_eq(mx.value, [5])

    rt.insert("INSERT INTO nums(n) VALUES (2)", {})
    assert_eq(mn.value, [2])
    assert_eq(mx.value, [5])

    rt.insert("INSERT INTO nums(n) VALUES (10)", {})
    assert_eq(mx.value, [10])

    rid = conn.execute("SELECT id FROM nums WHERE n=2").fetchone()[0]
    rt.update("UPDATE nums SET n=7 WHERE id=:id", {"id": rid})
    assert_eq(mn.value, [5])

    rid = conn.execute("SELECT id FROM nums WHERE n=10").fetchone()[0]
    rt.update("UPDATE nums SET n=1 WHERE id=:id", {"id": rid})
    assert_eq(mn.value, [1])
    assert_eq(mx.value, [7])

    rid = conn.execute("SELECT id FROM nums WHERE n=7").fetchone()[0]
    rt.delete("DELETE FROM nums WHERE id=:id", {"id": rid})
    assert_eq(mx.value, [5])

    rid = conn.execute("SELECT id FROM nums WHERE n=1").fetchone()[0]
    rt.delete("DELETE FROM nums WHERE id=:id", {"id": rid})
    assert_eq(mn.value, [5])


def test_aggregate_constant_expression():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    ag = Aggregate(rt, ("COUNT(*)", "42"))
    events = []
    ag.listeners.append(events.append)

    assert_eq(ag.value, [0, 42])

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert_eq(ag.value, [1, 42])
    assert_eq(events[-1], [3, [0, 42], [1, 42]])


def test_aggregate_group_by():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, grp INTEGER, n INTEGER)")
    rt = ReactiveTable(conn, "nums")
    ag = Aggregate(rt, ("COUNT(*)", "SUM(n)"), group_by="grp")
    events = []
    ag.listeners.append(events.append)

    rt.insert("INSERT INTO nums(grp,n) VALUES (1,10)", {})
    assert_eq(events[-1], [1, (1, 1, 10)])

    rt.insert("INSERT INTO nums(grp,n) VALUES (1,5)", {})
    assert_eq(events[-1], [3, (1, 1, 10), (1, 2, 15)])

    rid = conn.execute("SELECT id FROM nums WHERE n=5").fetchone()[0]
    rt.update("UPDATE nums SET grp=2 WHERE id=:id", {"id": rid})
    assert events[-2:] == [[3, (1, 2, 15), (1, 1, 10)], [1, (2, 1, 5)]]

    rid = conn.execute("SELECT id FROM nums WHERE grp=1").fetchone()[0]
    rt.delete("DELETE FROM nums WHERE id=:id", {"id": rid})
    assert_eq(events[-1], [2, (1, 1, 10)])

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

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rt.insert("INSERT INTO items(name) VALUES ('y')", {})
    assert_eq(seen[-1], [1, (1, 'x')])

    rid = conn.execute("SELECT id FROM items WHERE name='y'").fetchone()[0]
    rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": rid})
    assert_eq(seen[-1], [1, (rid, 'x')])


def test_unionall():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = UnionAll(r1, r2)
    seen = []
    u.listeners.append(seen.append)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    r2.insert("INSERT INTO b(name) VALUES ('y')", {})
    assert_eq([e[1][1] for e in seen], ['x', 'y'])


def test_select():
    conn, rt = _db(), None
    rt = ReactiveTable(conn, "items")
    sel = Select(rt, "name")
    seen = []
    sel.listeners.append(seen.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert_eq(seen[-1], [1, ('x',)])

    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": rid})
    assert_eq(seen[-1], [3, ('x',), ('y',)])


# Additional tests
def test_count_all_decrement():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt)
    events = []
    cnt.listeners.append(events.append)

    # insert two rows
    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rt.insert("INSERT INTO items(name) VALUES ('y')", {})
    assert_eq(cnt.value, [2])

    # delete one row
    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.delete("DELETE FROM items WHERE id = :id", {"id": rid})
    assert_eq(cnt.value, [1])
    assert_eq(events[-1], [3, [2], [1]])


def test_countall_multiple_expressions():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = Aggregate(rt, ("COUNT(*)", "COUNT(name)"))
    events = []
    cnt.listeners.append(events.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert_eq(cnt.value, [1, 1])
    assert_eq(events[-1], [3, [0, 0], [1, 1]])

    rt.insert("INSERT INTO items(name) VALUES (NULL)", {})
    assert_eq(cnt.value, [2, 1])
    assert_eq(events[-1], [3, [1, 1], [2, 1]])


def test_where_remove():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w = Where(rt, "name = 'x'")
    events = []
    w.listeners.append(events.append)

    # insert a matching row
    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    # update it so it no longer matches the predicate
    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": rid})
    assert_eq(events[-1], [2, (1, 'x')])


def test_select_no_change_on_same_value_update():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    sel = Select(rt, "name")
    events = []
    sel.listeners.append(events.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    initial_event_count = len(events)

    # update without changing the selected value
    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": rid})
    assert_eq(len(events), initial_event_count)  # no new event emitted


def test_where_no_event_on_same_value_update():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w = Where(rt, "name = 'x'")
    events = []
    w.listeners.append(events.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    initial_len = len(events)

    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": rid})

    assert_eq(len(events), initial_len)


def test_reactive_table_no_event_on_same_value_update():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    events = []
    rt.listeners.append(events.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    initial_len = len(events)

    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.update("UPDATE items SET name='x' WHERE id=:id", {"id": rid})

    assert_eq(len(events), initial_len)


def test_unionall_update():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = UnionAll(r1, r2)
    events = []
    u.listeners.append(events.append)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    rid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r1.update("UPDATE a SET name='y' WHERE id=:id", {"id": rid})
    assert_eq(events[-1], [3, (1, 'x'), (1, 'y')])


def test_update_without_where_clause():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rt.update("UPDATE items SET name='z'", {})
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

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    r2.insert("INSERT INTO b(name) VALUES ('x')", {})  # duplicate
    r2.insert("INSERT INTO b(name) VALUES ('y')", {})
    assert_eq([e[1][1] for e in events], ["x", "y"])


def test_union_update():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = Union(r1, r2)
    events = []
    u.listeners.append(events.append)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    rid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r1.update("UPDATE a SET name='y' WHERE id=:id", {"id": rid})
    assert_eq(events[-1], [3, (1, 'x'), (1, 'y')])


def test_union_update_with_duplicate():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    u = Union(r1, r2)
    events = []
    u.listeners.append(events.append)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    r2.insert("INSERT INTO b(name) VALUES ('x')", {})
    rid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    events.clear()
    r1.update("UPDATE a SET name='y' WHERE id=:id", {"id": rid})
    assert_eq(events, [[1, (1, 'y')]])


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
    conn, r1, r2, events = _make_join()

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE a_id=:a", {"a": aid}).fetchone()[0]

    assert_eq(events, [[1, (aid, 'x', bid, aid, 't')]])


def test_join_update():
    conn, r1, r2, events = _make_join()

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't1')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE title='t1'").fetchone()[0]
    events.clear()

    r2.update("UPDATE b SET title='t2' WHERE id=:id", {"id": bid})
    assert_eq(events, [[3, (aid, 'x', bid, aid, 't1'), (aid, 'x', bid, aid, 't2')]])


def test_join_update_no_change():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    j = Join(r1, r2, "a.id = b.a_id")
    events = []
    j.listeners.append(events.append)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't1')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE title='t1'").fetchone()[0]
    events.clear()

    r2.update("UPDATE b SET title='t1' WHERE id=:id", {"id": bid})
    assert events == []


def test_join_delete():
    conn, r1, r2, events = _make_join()

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE a_id=:a", {"a": aid}).fetchone()[0]
    events.clear()

    r2.delete("DELETE FROM b WHERE id=:id", {"id": bid})
    assert_eq(events, [[2, (aid, 'x', bid, aid, 't')]])
    events.clear()

    r1.delete("DELETE FROM a WHERE id=:id", {"id": aid})
    assert events == []


def test_left_outer_join_basic():
    conn, r1, r2, events = _make_join(left=True)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    assert_eq(events, [[1, (aid, 'x', None, None, None)]])
    events.clear()

    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE a_id=:a", {"a": aid}).fetchone()[0]
    assert_eq(events, [[3, (aid, 'x', None, None, None), (aid, 'x', bid, aid, 't')]])


def test_left_outer_join_update_delete():
    conn, r1, r2, events = _make_join(left=True)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't1')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE title='t1'").fetchone()[0]
    events.clear()

    r2.update("UPDATE b SET title='t2' WHERE id=:id", {"id": bid})
    assert_eq(events, [[3, (aid, 'x', bid, aid, 't1'), (aid, 'x', bid, aid, 't2')]])
    events.clear()

    r2.delete("DELETE FROM b WHERE id=:id", {"id": bid})
    assert_eq(events, [[3, (aid, 'x', bid, aid, 't2'), (aid, 'x', None, None, None)]])
    events.clear()

    r1.delete("DELETE FROM a WHERE id=:id", {"id": aid})
    assert_eq(events, [[2, (aid, 'x', None, None, None)]])


def test_right_outer_join_basic():
    conn, r1, r2, events = _make_join(right=True)

    r2.insert("INSERT INTO b(a_id, title) VALUES (1, 't')", {})
    bid = conn.execute("SELECT id FROM b WHERE title='t'").fetchone()[0]
    assert_eq(events, [[1, (None, None, bid, 1, 't')]])
    events.clear()

    r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {})
    aid = 1
    assert_eq(events, [[3, (None, None, bid, 1, 't'), (aid, 'x', bid, 1, 't')]])


def test_right_outer_join_update_delete():
    conn, r1, r2, events = _make_join(right=True)

    r2.insert("INSERT INTO b(a_id, title) VALUES (1, 't1')", {})
    bid = conn.execute("SELECT id FROM b WHERE title='t1'").fetchone()[0]
    r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {})
    aid = 1
    events.clear()

    r1.update("UPDATE a SET name='y' WHERE id=1", {})
    assert_eq(events, [[3, (aid, 'x', bid, 1, 't1'), (aid, 'y', bid, 1, 't1')]])
    events.clear()

    r1.delete("DELETE FROM a WHERE id=1", {})
    assert_eq(events, [[3, (aid, 'y', bid, 1, 't1'), (None, None, bid, 1, 't1')]])
    events.clear()

    r2.delete("DELETE FROM b WHERE id=:id", {"id": bid})
    assert_eq(events, [[2, (None, None, bid, 1, 't1')]])


def test_full_outer_join_left_then_right():
    conn, r1, r2, events = _make_join(left=True, right=True)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    assert_eq(events, [[1, (aid, 'x', None, None, None)]])
    events.clear()

    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE a_id=:a", {"a": aid}).fetchone()[0]
    assert_eq(events, [[3, (aid, 'x', None, None, None), (aid, 'x', bid, aid, 't')]])


def test_full_outer_join_right_then_left():
    conn, r1, r2, events = _make_join(left=True, right=True)

    r2.insert("INSERT INTO b(a_id, title) VALUES (1, 't1')", {})
    bid = conn.execute("SELECT id FROM b WHERE title='t1'").fetchone()[0]
    assert_eq(events, [[1, (None, None, bid, 1, 't1')]])
    events.clear()

    r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {})
    aid = 1
    assert_eq(events, [[3, (None, None, bid, 1, 't1'), (aid, 'x', bid, 1, 't1')]])


def test_full_outer_join_update_delete():
    conn, r1, r2, events = _make_join(left=True, right=True)

    r2.insert("INSERT INTO b(a_id, title) VALUES (1, 't1')", {})
    bid = conn.execute("SELECT id FROM b WHERE title='t1'").fetchone()[0]
    assert_eq(events, [[1, (None, None, bid, 1, 't1')]])
    events.clear()

    r1.insert("INSERT INTO a(id, name) VALUES (1, 'x')", {})
    aid = 1
    assert_eq(events, [[3, (None, None, bid, 1, 't1'), (aid, 'x', bid, 1, 't1')]])
    events.clear()

    r2.update("UPDATE b SET title='t2' WHERE id=:id", {"id": bid})
    assert_eq(events, [[3, (aid, 'x', bid, 1, 't1'), (aid, 'x', bid, 1, 't2')]])
    events.clear()

    r1.delete("DELETE FROM a WHERE id=1", {})
    assert_eq(events, [[3, (aid, 'x', bid, 1, 't2'), (None, None, bid, 1, 't2')]])
    events.clear()

    r2.delete("DELETE FROM b WHERE id=:id", {"id": bid})
    assert_eq(events, [[2, (None, None, bid, 1, 't2')]])


def test_intersect_deduplication():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    s1, s2 = Select(r1, "name"), Select(r2, "name")
    inter = Intersect(s1, s2)
    events = []
    inter.listeners.append(events.append)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    r1.insert("INSERT INTO a(name) VALUES ('x')", {})  # duplicate in same table
    r2.insert("INSERT INTO b(name) VALUES ('x')", {})

    assert_eq(events, [[1, ('x',)]])


def test_intersect_update_with_remaining_duplicate():
    """Updating one of several matching rows shouldn't emit a delete."""
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    inter = Intersect(Select(r1, "name"), Select(r2, "name"))
    events = []
    inter.listeners.append(events.append)

    r1.insert("INSERT INTO a(name) VALUES ('z')", {})
    r2.insert("INSERT INTO b(name) VALUES ('x')", {})
    r1.update("UPDATE a SET name='x' WHERE id=1", {})
    r1.insert("INSERT INTO a(name) VALUES ('x')", {})

    events.clear()
    r1.update("UPDATE a SET name='z' WHERE id=1", {})

    assert events == []
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

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert_eq(dv.value, 1)
    assert_eq(seen[-1], 1)

    sel = Select(rt, "name")
    dv.reset(sel)
    assert dv.onevent not in cnt.listeners
    assert_eq(dv.value, "x")
    assert_eq(seen[-1], "x")

    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": rid})
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

    def cb():
        rt.insert("INSERT INTO items(name) VALUES ('x')", {})
        rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
        rt.update("UPDATE items SET name='y' WHERE id=:id", {"id": rid})
        rt.delete("DELETE FROM items WHERE id=:id", {"id": rid})

    check_component(rt, cb)


def test_check_component_where():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    w = Where(rt, "name = 'x'")

    def cb():
        rt.insert("INSERT INTO items(name) VALUES ('x')", {})
        rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
        rt.update("UPDATE items SET name='z' WHERE id=:id", {"id": rid})

    check_component(w, cb)


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
    """Perform a random insert, delete, or update on *rt*."""
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
        if isinstance(parents, tuple):
            def cb():
                for _ in range(iterations):
                    _random_op(random.choice(parents))
        else:
            def cb():
                for _ in range(iterations):
                    _random_op(parents)
        check_component(comp, cb)


def test_fuzz_components():
    fuzz_components(iterations=10, seed=123)
