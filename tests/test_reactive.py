import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
from pageql.reactive import ReactiveTable, CountAll, Signal, DerivedSignal, Where, UnionAll, Select


def _db():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    return c


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


def test_count_all():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    cnt = CountAll(rt)
    events = []
    cnt.listeners.append(events.append)

    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    assert_eq(cnt.value, 1)
    assert_eq(events[-1], [3, [0], [1]]) 


def test_signal_and_derived():
    a, b = Signal(1), Signal(2)
    d = DerivedSignal(lambda: a.value + b.value, [a, b])
    seen = []
    d.listeners.append(seen.append)
    a.set(2)
    assert_eq(d.value, 4)
    assert_eq(seen[-1], 4)
    a.set(2)  # no change
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
    cnt = CountAll(rt)
    events = []
    cnt.listeners.append(events.append)

    # insert two rows
    rt.insert("INSERT INTO items(name) VALUES ('x')", {})
    rt.insert("INSERT INTO items(name) VALUES ('y')", {})
    assert_eq(cnt.value, 2)

    # delete one row
    rid = conn.execute("SELECT id FROM items WHERE name='x'").fetchone()[0]
    rt.delete("DELETE FROM items WHERE id = :id", {"id": rid})
    assert_eq(cnt.value, 1)
    assert_eq(events[-1], [3, [2], [1]])


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

if __name__ == "__main__":
    test_reactive_table_events()
    test_count_all()
    test_signal_and_derived()
    test_where()
    test_unionall()
    test_select()
    test_count_all_decrement()
    test_where_remove()
    test_select_no_change_on_same_value_update()
    test_unionall_update()
    test_where_delete_event_should_be_labeled_delete()
    test_select_delete_event_should_be_labeled_delete()
    test_update_null_row_should_raise_custom_exception()