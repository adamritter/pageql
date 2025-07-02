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

def _delete_event_should_be_labeled_delete(factory):
    conn = _db()
    tables = Tables(conn)
    rt = tables._get("items")
    comp = factory(rt)

    test_sqls(
        comp,
        tables,
        [
            "INSERT INTO items(id,name) VALUES (1,'x')",
            "DELETE FROM items WHERE id = 1",
        ],
    )


def test_where_delete_event_should_be_labeled_delete():
    """Deleting a matching row should emit a delete event."""
    _delete_event_should_be_labeled_delete(lambda rt: Where(rt, "name = 'x'"))


def test_select_delete_event_should_be_labeled_delete():
    """Deleting a parent row should emit a delete event for the projection."""
    _delete_event_should_be_labeled_delete(lambda rt: Select(rt, "name"))
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
    tables = Tables(conn)
    r1, r2 = tables._get("a"), tables._get("b")
    j = Join(r1, r2, "a.id = b.a_id", left_outer=left, right_outer=right)
    return conn, tables, r1, r2, j


def _items_rt():
    conn = _db()
    tables = Tables(conn)
    return tables._get("items"), tables


def _nums_rt():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    tables = Tables(conn)
    return tables._get("nums"), tables


def _nums_grp_rt():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, grp INTEGER, n INTEGER)")
    tables = Tables(conn)
    return tables._get("nums"), tables


def _select_comp():
    rt, tables = _items_rt()
    return Select(rt, "name"), tables


def _where_comp():
    rt, tables = _items_rt()
    return Where(rt, "name = 'x'"), tables


def _agg_count_all():
    rt, tables = _items_rt()
    return Aggregate(rt), tables


def _agg_count_name():
    rt, tables = _items_rt()
    return Aggregate(rt, ("COUNT(name)",)), tables


def _agg_sum():
    rt, tables = _nums_rt()
    return Aggregate(rt, ("SUM(n)",)), tables


def _agg_avg():
    rt, tables = _nums_rt()
    return Aggregate(rt, ("AVG(n)",)), tables


def _agg_group_by():
    rt, tables = _nums_grp_rt()
    return Aggregate(rt, ("COUNT(*)", "SUM(n)"), group_by="grp"), tables


def _agg_countall_multi():
    rt, tables = _items_rt()
    return Aggregate(rt, ("COUNT(*)", "COUNT(name)")), tables


def _unionall_comp():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    tables = Tables(conn)
    r1, r2 = tables._get("a"), tables._get("b")
    return UnionAll(r1, r2), tables


def _union_comp():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    tables = Tables(conn)
    r1, r2 = tables._get("a"), tables._get("b")
    return Union(r1, r2), tables


def _intersect_comp():
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    tables = Tables(conn)
    r1, r2 = tables._get("a"), tables._get("b")
    return Intersect(Select(r1, "name"), Select(r2, "name")), tables


def _join_comp(left=False, right=False):
    def _inner():
        _, tables, _, _, j = _make_join(left=left, right=right)
        return j, tables
    return _inner


def _join_no_change():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER, title TEXT)")
    tables = Tables(conn)
    r1, r2 = tables._get("a"), tables._get("b")
    return Join(r1, r2, "a.id = b.a_id"), tables


_ITEMS_SEQUENCE = [
    "INSERT INTO items(id,name) VALUES (1,'a')",
    "UPDATE items SET name='b' WHERE id=1",
    "DELETE FROM items WHERE id=1",
    "INSERT INTO items(id,name) VALUES (2,'x')",
    "INSERT INTO items(id,name) VALUES (3,'x')",
    "DELETE FROM items WHERE name='x'",
    "INSERT INTO items(id,name) VALUES (4,NULL)",
    "UPDATE items SET name='y' WHERE id=4",
    "UPDATE items SET name=NULL WHERE id=4",
    "INSERT INTO items(id,name) VALUES (5,'z')",
    "UPDATE items SET name='z' WHERE id=5",
]


_NUMS_SEQUENCE = [
    "INSERT INTO nums(id,n) VALUES (1,1)",
    "INSERT INTO nums(id,n) VALUES (2,2)",
    "UPDATE nums SET n=5 WHERE id=2",
    "DELETE FROM nums WHERE id=2",
    "INSERT INTO nums(id,n) VALUES (3,10)",
    "UPDATE nums SET n=7 WHERE id=3",
]

_GROUP_SEQUENCE = [
    "INSERT INTO nums(id,grp,n) VALUES (1,1,10)",
    "INSERT INTO nums(id,grp,n) VALUES (2,1,5)",
    "UPDATE nums SET grp=2 WHERE id=2",
    "DELETE FROM nums WHERE id=1",
    "INSERT INTO nums(id,grp,n) VALUES (3,2,7)",
    "SELECT 1",
]

_UNION_SEQUENCE = [
    "INSERT INTO a(id,name) VALUES (1,'x')",
    "INSERT INTO b(id,name) VALUES (1,'x')",
    "INSERT INTO b(id,name) VALUES (2,'y')",
    "UPDATE a SET name='z' WHERE id=1",
    "DELETE FROM b WHERE id=2",
]

_JOIN_SEQUENCE = [
    "INSERT INTO a(id,name) VALUES (1,'x')",
    "INSERT INTO b(id,a_id,title) VALUES (1,1,'t1')",
    "INSERT INTO b(id,a_id,title) VALUES (2,1,'t2')",
    "UPDATE b SET title='t3' WHERE id=1",
    "UPDATE b SET title='t3' WHERE id=1",
    "DELETE FROM b WHERE id=2",
    "DELETE FROM a WHERE id=1",
]

_INTERSECT_SEQUENCE = [
    "INSERT INTO a(name) VALUES ('x')",
    "INSERT INTO a(name) VALUES ('x')",
    "INSERT INTO b(name) VALUES ('y')",
    "UPDATE b SET name='x' WHERE name='y'",
    "INSERT INTO b(name) VALUES ('x')",
]

_AB_SEQUENCE = _UNION_SEQUENCE + _INTERSECT_SEQUENCE

_SQL_CASE_GROUPS = [
    (_ITEMS_SEQUENCE, _items_rt, [
        "reactive_table_events", "reactive_table_delete_multiple_rows", "reactive_table_no_event_on_same_value_update"
    ]),
    (_ITEMS_SEQUENCE, _select_comp, ["select", "select_no_change_on_same_value_update"]),
    (_ITEMS_SEQUENCE, _where_comp, ["where_remove", "where_no_event_on_same_value_update"]),
    (_ITEMS_SEQUENCE, _agg_count_all, ["count_all"]),
    (_ITEMS_SEQUENCE, _agg_count_name, ["count_expression"]),
    (_ITEMS_SEQUENCE, _agg_countall_multi, ["countall_multiple_expressions"]),
    (_NUMS_SEQUENCE, _agg_sum, ["sum_expression"]),
    (_NUMS_SEQUENCE, _agg_avg, ["avg_expression"]),
    (_GROUP_SEQUENCE, _agg_group_by, ["aggregate_group_by"]),
    (_AB_SEQUENCE, _unionall_comp, ["unionall", "unionall_update"]),
    (_AB_SEQUENCE, _union_comp, ["union", "union_update", "union_update_with_duplicate"]),
    (_JOIN_SEQUENCE, _join_comp(), ["join_basic", "join_update", "join_delete"]),
    (_JOIN_SEQUENCE, _join_no_change, ["join_update_no_change"]),
    (_JOIN_SEQUENCE, _join_comp(left=True), ["left_outer_join_basic", "left_outer_join_update_delete"]),
    (_JOIN_SEQUENCE, _join_comp(right=True), ["right_outer_join_basic", "right_outer_join_update_delete"]),
    (_JOIN_SEQUENCE, _join_comp(left=True, right=True), [
        "full_outer_join_left_then_right", "full_outer_join_right_then_left", "full_outer_join_update_delete"
    ]),
    (_AB_SEQUENCE, _intersect_comp, ["intersect_deduplication"]),
]

_SQL_CASES = [
    (name, factory, sql)
    for sql, factory, names in _SQL_CASE_GROUPS
    for name in names
]


@pytest.mark.parametrize("factory,sqls", [(f, s) for _, f, s in _SQL_CASES], ids=[n for n, _, _ in _SQL_CASES])
def test_component_sqls(factory, sqls):
    comp, tables = factory()
    test_sqls(comp, tables, sqls)


def test_min_max_expression():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nums(id INTEGER PRIMARY KEY, n INTEGER)")
    tables = Tables(conn)
    rt = tables._get("nums")
    mn = Aggregate(rt, ("MIN(n)",))
    mx = Aggregate(rt, ("MAX(n)",))

    test_sqls(
        mn,
        tables,
        [
            "INSERT INTO nums(id,n) VALUES (1,5)",
            "INSERT INTO nums(id,n) VALUES (2,2)",
            "INSERT INTO nums(id,n) VALUES (3,10)",
            "UPDATE nums SET n=7 WHERE id=2",
            "UPDATE nums SET n=1 WHERE id=3",
            "DELETE FROM nums WHERE id=2",
            "DELETE FROM nums WHERE id=3",
        ],
    )

    assert_eq(mx.value, [5])
    assert_eq(mn.value, [5])


def test_aggregate_constant_expression():
    conn = _db()
    tables = Tables(conn)
    rt = tables._get("items")
    ag = Aggregate(rt, ("COUNT(*)", "42"))

    assert_eq(ag.value, [0, 42])

    test_sqls(
        ag,
        tables,
        ["INSERT INTO items(name) VALUES ('x')"],
    )
    assert_eq(ag.value, [1, 42])


def test_count_all_decrement():
    conn = _db()
    tables = Tables(conn)
    rt = tables._get("items")
    cnt = Aggregate(rt)

    test_sqls(
        cnt,
        tables,
        [
            "INSERT INTO items(id,name) VALUES (1,'x')",
            "INSERT INTO items(id,name) VALUES (2,'y')",
            "DELETE FROM items WHERE id=1",
        ],
    )
    assert_eq(cnt.value, [1])


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




def test_intersect_update_with_remaining_duplicate():
    """Updating one of several matching rows shouldn't emit a delete."""
    conn = sqlite3.connect(":memory:")
    for t in ("a", "b"):
        conn.execute(f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, name TEXT)")
    tables = Tables(conn)
    r1, r2 = tables._get("a"), tables._get("b")
    inter = Intersect(Select(r1, "name"), Select(r2, "name"))

    test_sqls(
        inter,
        tables,
        [
            "INSERT INTO a(name) VALUES ('z')",
            "INSERT INTO b(name) VALUES ('x')",
            "UPDATE a SET name='x' WHERE id=1",
            "INSERT INTO a(name) VALUES ('x')",
            "UPDATE a SET name='z' WHERE id=1",
        ],
    )

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


