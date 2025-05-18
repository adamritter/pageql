import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL
from pageql.reactive import DerivedSignal


def test_render_nonexistent_returns_404():
    r = PageQL(":memory:")
    result = r.render("/nonexistent")
    assert result.status_code == 404


def test_reactive_toggle():
    r = PageQL(":memory:")
    r.load_module("reactive", "{{reactive}} {{#reactive on}}{{reactive}} {{#reactive off}}{{reactive}}")
    result = r.render("/reactive")
    assert result.body.strip() == "False True False"


def test_set_signal_reactive_on():
    r = PageQL(":memory:")
    r.load_module("sig", "{{#reactive on}}{{#set foo 42}}")
    s = DerivedSignal(lambda: 0, [])
    r.render("/sig", {"foo": s})
    assert s.value == 42


def test_set_signal_derived_replace():
    r = PageQL(":memory:")
    r.load_module("sig", "{{#reactive on}}{{#set foo 1}}")
    sig = DerivedSignal(lambda: 0, [])
    r.render("/sig", {"foo": sig})
    assert sig.value == 1

    r.load_module("sig", "{{#reactive on}}{{#set foo 2}}")
    r.render("/sig", {"foo": sig})
    assert sig.value == 2


def test_render_derived_signal_value_and_eval():
    r = PageQL(":memory:")
    sig = DerivedSignal(lambda: 1, [])
    r.load_module("m", "{{foo}} {{:foo + :foo}}")
    result = r.render("/m", {"foo": sig})
    assert result.body.strip() == "1 2"


def test_from_reactive_uses_parse(monkeypatch):
    import pageql.reactive_sql as rsql

    seen = []
    original = rsql.parse_reactive

    def wrapper(sql, tables, params=None):
        seen.append(sql)
        return original(sql, tables, params)

    monkeypatch.setattr(rsql, "parse_reactive", wrapper)
    import pageql.pageql as pql
    monkeypatch.setattr(pql, "parse_reactive", wrapper)

    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module("m", "{{#reactive on}}{{#from items}}<{{id}}>{{/from}}")
    result = r.render("/m")
    assert seen == ["SELECT * FROM items"]
    expected = (
        "<script>window.pageqlMarkers={};document.currentScript.remove()</script>"
        "<!--pageql-start:0--><script>(window.pageqlMarkers||(window.pageqlMarkers={}))[0]=document.currentScript.previousSibling;document.currentScript.remove()</script><1>\n<2>\n"
        "<!--pageql-end:0--><script>window.pageqlMarkers[0].e="
        "document.currentScript.previousSibling;document.currentScript.remove()</script>"
    )
    assert result.body == expected


if __name__ == "__main__":
    test_render_nonexistent_returns_404()
