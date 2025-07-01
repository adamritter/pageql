import sys
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL


def setup_items(r):
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])


def test_from_cachable_true_with_column_param():
    r = PageQL(":memory:")
    setup_items(r)
    r.load_module(
        "m",
        "{%reactive on%}{%from items%}{%if :name%}x{%endif%}{%endfrom%}",
    )
    result = r.render("/m")
    listener = result.context.listeners[0][1]
    assert listener.__kwdefaults__["extra_cache_key"] == ""


def test_from_cachable_false_with_external_param():
    r = PageQL(":memory:")
    setup_items(r)
    r.load_module(
        "m",
        "{%reactive on%}{%from items%}{%if :other%}x{%endif%}{%endfrom%}",
    )
    result = r.render("/m", params={"other": 1})
    listener = result.context.listeners[0][1]
    assert listener.__kwdefaults__["extra_cache_key"] == '{"other": 1}'
