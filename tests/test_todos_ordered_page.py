import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pathlib import Path
from pageql.pageql import PageQL

def test_todos_ordered_by_text():
    src = Path("website/todos_ordered.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("todos_ordered", src)
    r.db.execute(
        "CREATE TABLE IF NOT EXISTS todos(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, completed INTEGER DEFAULT 0 CHECK(completed IN (0,1)))"
    )
    r.db.execute("INSERT INTO todos(text) VALUES ('b'), ('a')")
    result = r.render("/todos_ordered", reactive=False)
    body = result.body
    assert body.index(">a</label>") < body.index(">b</label>")
