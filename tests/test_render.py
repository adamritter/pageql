import sys
from pathlib import Path
import base64
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
    expected = (
        "False "
        "<script>pstart(0)</script>True"
        "<script>pend(0)</script> False"
    )
    assert result.body == expected


def test_reactive_count_with_param_dependency():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table nums(value INTEGER)}}"
        "{{#insert into nums(value) values (1)}}"
        "{{#insert into nums(value) values (2)}}"
        "{{#insert into nums(value) values (3)}}"
        "{{#reactive on}}"
        "{{#set a 1}}"
        "{{#set cnt count(*) from nums where value > :a}}"
        "{{cnt}}"
        "{{#set a 2}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        ""
        "<script>pstart(0)</script>2<script>pend(0)</script>"
        "<script>pset(0,\"1\")</script>"
    )
    assert result.body == expected


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
    import hashlib
    h1 = base64.b64encode(hashlib.sha256(repr((1,"a",)).encode()).digest())[:8]
    h2 = base64.b64encode(hashlib.sha256(repr((2,"b",)).encode()).digest())[:8]
    expected = (
        ""
        f"<script>pstart('0_{h1}')</script><1><script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script><2><script>pend('0_{h2}')</script>\n"
    )
    assert result.body == expected




def test_reactive_set_comments():
    snippet = """{{#reactive on}}
{{#set a 1}}
{{a}}
{{:a + :a}}
{{#set b 3}}
<p>{{:a + :b}} = 4</p>
{{#set c :a+:b}}
<p>{{:c}} = c = 4</p>
{{#set a 2}}
<p>{{:a + :b}} = 5</p>
<p>{{:c}} = c = 5</p>
{{#reactive off}}"""

    r = PageQL(":memory:")
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "\n"
        "<script>pstart(0)</script>1<script>pend(0)</script>\n"
        "<script>pstart(1)</script>2<script>pend(1)</script>\n"
        "<p><script>pstart(2)</script>4<script>pend(2)</script> = 4</p>\n"
        "<p><script>pstart(3)</script>4<script>pend(3)</script> = c = 4</p>\n"
        "<script>pset(0,\"2\")</script><script>pset(3,\"5\")</script>\n"
        "<p><script>pstart(4)</script>5<script>pend(4)</script> = 5</p>\n"
        "<p><script>pstart(5)</script>5<script>pend(5)</script> = c = 5</p>\n"
    )
    assert result.body == expected


def test_from_reactive_delete_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module("m", "{{#reactive on}}{{#from items}}<{{id}}>{{/from}}{{#delete from items where id=1}}")
    result = r.render("/m")
    import hashlib
    h1 = base64.b64encode(hashlib.sha256(repr((1,"a",)).encode()).digest())[:8]
    h2 = base64.b64encode(hashlib.sha256(repr((2,"b",)).encode()).digest())[:8]
    expected = (
        ""
        f"<script>pstart('0_{h1}')</script><1><script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script><2><script>pend('0_{h2}')</script>\n"
        f"<script>pdelete('0_{h1}')</script>"
    )
    assert result.body == expected


def test_from_reactive_update_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items}}<{{name}}>{{/from}}{{#update items set name='c' where id=1}}",
    )
    result = r.render("/m")
    import hashlib

    h1_old = base64.b64encode(hashlib.sha256(repr((1, "a",)).encode()).digest())[:8]
    h1_new = base64.b64encode(hashlib.sha256(repr((1, "c",)).encode()).digest())[:8]
    h2 = base64.b64encode(hashlib.sha256(repr((2, "b",)).encode()).digest())[:8]
    expected = (
        f"<script>pstart('0_{h1_old}')</script><a><script>pend('0_{h1_old}')</script>\n"
        f"<script>pstart('0_{h2}')</script><b><script>pend('0_{h2}')</script>\n"
        f"<script>pupdate('0_{h1_old}','0_{h1_new}',\"<c>\")</script>"
    )
    assert result.body == expected
