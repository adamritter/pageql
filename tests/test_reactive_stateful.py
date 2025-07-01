import sqlite3
import sys
import types
import pytest
from pathlib import Path
from hypothesis.stateful import RuleBasedStateMachine, rule, run_state_machine_as_test
from hypothesis import strategies as st, assume, settings, HealthCheck

# Ensure import path and stub watchfiles
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

if sys.platform == "darwin":
    pytest.skip("unsupported platform", allow_module_level=True)

from pageql.reactive import (
    ReactiveTable,
    Where,
    Select,
    Aggregate,
    UnionAll,
    Union,
    Intersect,
)
from pageql.join import Join


class ReactiveStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.conn = sqlite3.connect(":memory:")
        self.conn_expected = sqlite3.connect(":memory:")
        for c in (self.conn, self.conn_expected):
            c.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
            c.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, name TEXT)")
            c.execute("CREATE TABLE b(id INTEGER PRIMARY KEY, name TEXT)")

        # Reactive tables
        self.rt_items = ReactiveTable(self.conn, "items")
        self.rt_a = ReactiveTable(self.conn, "a")
        self.rt_b = ReactiveTable(self.conn, "b")

        # Derived components
        self.where_items = Where(self.rt_items, "name LIKE 'x%'")
        self.select_items = Select(self.rt_items, "name")
        self.count_items = Aggregate(self.rt_items)
        self.union_all = UnionAll(self.rt_a, self.rt_b)
        self.union = Union(self.rt_a, self.rt_b)
        self.intersect = Intersect(self.rt_a, self.rt_b)
        self.join_ab = Join(self.rt_a, self.rt_b, "a.name = b.name")

        self.components = [
            self.rt_items,
            self.where_items,
            self.select_items,
            self.count_items,
            self.union_all,
            self.union,
            self.intersect,
            self.join_ab,
        ]

        self.next_id = {"items": 1, "a": 1, "b": 1}
        self.ids = {"items": set(), "a": set(), "b": set()}

    def _rt(self, table):
        return {
            "items": self.rt_items,
            "a": self.rt_a,
            "b": self.rt_b,
        }[table]

    def _assert_components(self):
        for comp in self.components:
            res = sorted(self.conn.execute(comp.sql).fetchall())
            exp = sorted(self.conn_expected.execute(comp.sql).fetchall())
            assert res == exp

    @rule(table=st.sampled_from(["items", "a", "b"]), name=st.sampled_from(["x", "y", "z"]))
    def insert_row(self, table, name):
        rid = self.next_id[table]
        self.next_id[table] += 1
        self.conn_expected.execute(f"INSERT INTO {table}(id, name) VALUES (?, ?)", (rid, name))
        rt = self._rt(table)
        rt.insert(f"INSERT INTO {table}(id, name) VALUES (:id, :name)", {"id": rid, "name": name})
        self.ids[table].add(rid)
        self._assert_components()

    @rule(table=st.sampled_from(["items", "a", "b"]), name=st.sampled_from(["x", "y", "z"]))
    def update_row(self, table, name):
        assume(self.ids[table])
        rid = next(iter(self.ids[table]))
        self.conn_expected.execute(f"UPDATE {table} SET name=? WHERE id=?", (name, rid))
        rt = self._rt(table)
        rt.update(f"UPDATE {table} SET name=:name WHERE id=:id", {"name": name, "id": rid})
        self._assert_components()

    @rule(
        table=st.sampled_from(["items", "a", "b"]),
        old=st.sampled_from(["x", "y", "z"]),
        new=st.sampled_from(["x", "y", "z"]),
    )
    def update_rows_by_name(self, table, old, new):
        assume(
            self.conn_expected.execute(
                f"SELECT 1 FROM {table} WHERE name=? LIMIT 1",
                (old,),
            ).fetchone()
        )
        self.conn_expected.execute(
            f"UPDATE {table} SET name=? WHERE name=?",
            (new, old),
        )
        rt = self._rt(table)
        rt.update(
            f"UPDATE {table} SET name=:new WHERE name=:old",
            {"new": new, "old": old},
        )
        self._assert_components()

    @rule(table=st.sampled_from(["items", "a", "b"]))
    def delete_row(self, table):
        assume(self.ids[table])
        rid = next(iter(self.ids[table]))
        self.conn_expected.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
        rt = self._rt(table)
        rt.delete(f"DELETE FROM {table} WHERE id=:id", {"id": rid})
        self.ids[table].remove(rid)
        self._assert_components()

    @rule(table=st.sampled_from(["items", "a", "b"]), name=st.sampled_from(["x", "y", "z"]))
    def delete_rows_by_name(self, table, name):
        rows = self.conn_expected.execute(
            f"SELECT id FROM {table} WHERE name=?",
            (name,),
        ).fetchall()
        assume(rows)
        self.conn_expected.execute(
            f"DELETE FROM {table} WHERE name=?",
            (name,),
        )
        rt = self._rt(table)
        rt.delete(
            f"DELETE FROM {table} WHERE name=:name",
            {"name": name},
        )
        for rid, in rows:
            self.ids[table].remove(rid)
        self._assert_components()


def test_reactive_state_machine():
    run_state_machine_as_test(
        ReactiveStateMachine,
        settings=settings(
            max_examples=10,
            deadline=None,
            stateful_step_count=10,
            suppress_health_check=(HealthCheck.filter_too_much,),
        ),
    )
