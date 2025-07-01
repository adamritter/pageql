import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.pageql import PageQL


def test_from_sets_first_row_param():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER)")
    r.db.executemany("INSERT INTO items(id) VALUES (?)", [(1,), (2,)])
    r.load_module("m", "{%from items ORDER BY id%}{{:__first_row}} {{id}}{%endfrom%}")
    result = r.render("/m", reactive=False)
    assert result.body == "True 1\nFalse 2\n"

