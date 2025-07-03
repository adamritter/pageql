import sys
from pathlib import Path
import sqlite3

# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageql.reactive import ReactiveTable, Where, Order


def test_reactive_table_unique_columns():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE items(id INTEGER PRIMARY KEY, "
        "email TEXT UNIQUE, phone TEXT, UNIQUE(phone))"
    )
    rt = ReactiveTable(conn, "items")
    assert rt.unique_columns == {"id", "email", "phone"}

    w = Where(rt, "email IS NOT NULL")
    assert w.unique_columns == {"id", "email", "phone"}

    o = Order(rt, "id")
    assert o.unique_columns == {"id", "email", "phone"}


def test_order_stops_after_unique_column():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE items(id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT)"
    )
    rt = ReactiveTable(conn, "items")
    order = Order(rt, "email")
    assert order._full_order_sql == "email"

    order2 = Order(rt, "name")
    assert order2._full_order_sql == "name, id"


def test_unique_columns_with_composite_index():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE items(item_id INTEGER, tag TEXT, value TEXT, "
        "PRIMARY KEY(item_id, tag))"
    )
    conn.execute("CREATE UNIQUE INDEX idx_tag_value ON items(tag, value)")
    rt = ReactiveTable(conn, "items")
    assert ("item_id", "tag") in rt.unique_columns
    assert ("tag", "value") in rt.unique_columns

    w = Where(rt, "tag IS NOT NULL")
    assert ("item_id", "tag") in w.unique_columns
    assert ("tag", "value") in w.unique_columns

    o = Order(rt, "tag")
    assert ("item_id", "tag") in o.unique_columns
    assert ("tag", "value") in o.unique_columns
