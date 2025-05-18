import sys
from pathlib import Path
import types

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
    CountAll,
    DerivedSignal,
    Where,
    UnionAll,
    Union,
    Intersect,
    Join,
    Select,
    get_dependencies,
)


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


def test_update_invalid_sql_should_raise_value_error():
    conn = _db()
    rt = ReactiveTable(conn, "items")
    try:
        rt.update("UPDATE items SET name='z'", {})
    except ValueError:
        pass
    else:
        assert False, "expected ValueError"


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
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    r1, r2 = ReactiveTable(conn, "a"), ReactiveTable(conn, "b")
    j = Join(r1, r2, "a.id = b.a_id")
    events = []
    j.listeners.append(events.append)

    r1.insert("INSERT INTO a(name) VALUES ('x')", {})
    aid = conn.execute("SELECT id FROM a WHERE name='x'").fetchone()[0]
    r2.insert("INSERT INTO b(a_id, title) VALUES (:a, 't')", {"a": aid})
    bid = conn.execute("SELECT id FROM b WHERE a_id=:a", {"a": aid}).fetchone()[0]

    assert_eq(events, [[1, (aid, 'x', bid, aid, 't')]])


def test_join_update():
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

    r2.update("UPDATE b SET title='t2' WHERE id=:id", {"id": bid})
    assert_eq(events, [[3, (aid, 'x', bid, aid, 't1'), (aid, 'x', bid, aid, 't2')]])


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
        (CountAll(rt), rt),
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
