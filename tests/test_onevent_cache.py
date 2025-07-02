import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageql.pageql import PageQL


def setup_items(r):
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])


def test_onevent_global_cache(monkeypatch):
    r = PageQL(":memory:")
    setup_items(r)
    r.load_module("m", "{%reactive on%}{%from items%}[{{name}}]{%endfrom%}")

    calls = []
    original = PageQL.process_nodes

    def wrapper(self, nodes, params, path, includes, http_verb=None, reactive=False, ctx=None, out=None):
        calls.append(True)
        return original(self, nodes, params, path, includes, http_verb, reactive, ctx, out)

    monkeypatch.setattr(PageQL, "process_nodes", wrapper)

    ctx1 = r.render("/m").context
    ctx2 = r.render("/m").context
    before = len(calls)

    r.tables.executeone("INSERT INTO items(name) VALUES ('c')", {})

    after = len(calls)
    ctx1.cleanup()
    ctx2.cleanup()
    assert after - before == 1
