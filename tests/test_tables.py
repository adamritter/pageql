import sys
from pathlib import Path
import sqlite3
import types

# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.reactive import Tables, ReactiveTable


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    return conn


def test_tables_executeone_events():
    conn = _db()
    tables = Tables(conn)
    rt = tables._get("items")
    events = []
    rt.listeners.append(events.append)

    tables.executeone("INSERT INTO items(name) VALUES (:n)", {"n": "a"})
    assert events[-1] == [1, (1, "a")]
    rid = events[-1][1][0]

    tables.executeone(
        "UPDATE items SET name = :n WHERE id = :id",
        {"n": "b", "id": rid},
    )
    assert events[-1] == [3, (1, "a"), (1, "b")]

    tables.executeone("DELETE FROM items WHERE id = :id", {"id": rid})
    assert events[-1] == [2, (1, "b")]

def test_tables_executeone_select():
    conn = _db()
    tables = Tables(conn)
    comp = tables.executeone("SELECT * FROM items", {})
    assert isinstance(comp, ReactiveTable)
    events = []
    comp.listeners.append(events.append)
    tables.executeone("INSERT INTO items(name) VALUES ('x')", {})
    assert events[-1] == [1, (1, 'x')]


def test_tables_executeone_invalid():
    conn = _db()
    tables = Tables(conn)
    try:
        tables.executeone("DROP TABLE items", {})
    except ValueError:
        pass
    else:
        assert False, "expected ValueError"

