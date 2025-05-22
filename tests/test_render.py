import sys
from pathlib import Path
import base64
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL, RenderContext
from pageql.reactive import DerivedSignal


def test_render_nonexistent_returns_404():
    r = PageQL(":memory:")
    result = r.render("/nonexistent")
    assert result.status_code == 404


def test_rendercontext_stops_rendering_and_collects_scripts():
    r = PageQL(":memory:")
    r.load_module("m", "hello")
    result = r.render("/m")
    ctx = result.context
    assert ctx.rendering is False
    assert ctx.scripts == []
    ctx.append_script("foo")
    assert ctx.scripts == ["foo"]
    assert ctx.out == []


def test_append_script_send_script():
    ctx = RenderContext()
    ctx.rendering = False
    sent = []
    ctx.send_script = sent.append
    ctx.append_script("bar")
    assert sent == ["bar"]
    assert ctx.scripts == []


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
        "{{#delete from nums where value = 3}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        ""
        "<script>pstart(0)</script>2<script>pend(0)</script>"
        "<script>pset(0,\"1\")</script>"
        "<script>pset(0,\"0\")</script>"
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
    r.load_module("m", "{{#reactive on}}{{#from items}}[{{id}}]{{/from}}")
    result = r.render("/m")
    assert seen == ["SELECT * FROM items"]
    import hashlib
    h1 = base64.b64encode(hashlib.sha256(repr((1,"a",)).encode()).digest())[:8].decode()
    h2 = base64.b64encode(hashlib.sha256(repr((2,"b",)).encode()).digest())[:8].decode()
    expected = (
        ""
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1}')</script>[1]<script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[2]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
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
        "<script>pset(0,\"2\")</script><script>pset(1,\"4\")</script><script>pset(2,\"5\")</script><script>pset(3,\"5\")</script>\n"
        "<p><script>pstart(4)</script>5<script>pend(4)</script> = 5</p>\n"
        "<p><script>pstart(5)</script>5<script>pend(5)</script> = c = 5</p>\n"
    )
    assert result.body == expected


def test_from_reactive_delete_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module("m", "{{#reactive on}}{{#from items}}[{{id}}]{{/from}}{{#delete from items where id=1}}")
    result = r.render("/m")
    import hashlib
    h1 = base64.b64encode(hashlib.sha256(repr((1,"a",)).encode()).digest())[:8].decode()
    h2 = base64.b64encode(hashlib.sha256(repr((2,"b",)).encode()).digest())[:8].decode()
    expected = (
        ""
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1}')</script>[1]<script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[2]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
        f"<script>pdelete('0_{h1}')</script>"
    )
    assert result.body == expected


def test_from_reactive_update_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items}}[{{name}}]{{/from}}{{#update items set name='c' where id=1}}",
    )
    result = r.render("/m")
    import hashlib

    h1_old = base64.b64encode(hashlib.sha256(repr((1, "a",)).encode()).digest())[:8].decode()
    h1_new = base64.b64encode(hashlib.sha256(repr((1, "c",)).encode()).digest())[:8].decode()
    h2 = base64.b64encode(hashlib.sha256(repr((2, "b",)).encode()).digest())[:8].decode()
    expected = (
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1_old}')</script>[a]<script>pend('0_{h1_old}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[b]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
        f"<script>pupdate('0_{h1_old}','0_{h1_new}',\"[c]\")</script>"
    )
    assert result.body == expected

def test_from_reactive_insert_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items}}[{{name}}]{{/from}}{{#insert into items(name) values ('c')}}",
    )
    result = r.render("/m")
    import hashlib

    h1 = base64.b64encode(hashlib.sha256(repr((1, "a",)).encode()).digest())[:8].decode()
    h2 = base64.b64encode(hashlib.sha256(repr((2, "b",)).encode()).digest())[:8].decode()
    h3 = base64.b64encode(hashlib.sha256(repr((3, "c",)).encode()).digest())[:8].decode()
    expected = (
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1}')</script>[a]<script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[b]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
        f"<script>pinsert('0_{h3}',\"[c]\")</script>"
    )
    assert result.body == expected


def test_from_nonreactive_delete_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items}}[{{id}}]{{/from}}{{#reactive off}}{{#delete from items where id=1}}",
    )
    result = r.render("/m")
    import hashlib

    h1 = base64.b64encode(hashlib.sha256(repr((1, "a",)).encode()).digest())[:8].decode()
    h2 = base64.b64encode(hashlib.sha256(repr((2, "b",)).encode()).digest())[:8].decode()
    expected = (
        ""
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1}')</script>[1]<script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[2]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
        f"<script>pdelete('0_{h1}')</script>"
    )
    assert result.body == expected


def test_from_nonreactive_update_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items}}[{{name}}]{{/from}}{{#reactive off}}{{#update items set name='c' where id=1}}",
    )
    result = r.render("/m")
    import hashlib

    h1_old = base64.b64encode(hashlib.sha256(repr((1, "a",)).encode()).digest())[:8].decode()
    h1_new = base64.b64encode(hashlib.sha256(repr((1, "c",)).encode()).digest())[:8].decode()
    h2 = base64.b64encode(hashlib.sha256(repr((2, "b",)).encode()).digest())[:8].decode()
    expected = (
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1_old}')</script>[a]<script>pend('0_{h1_old}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[b]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
        f"<script>pupdate('0_{h1_old}','0_{h1_new}',\"[c]\")</script>"
    )
    assert result.body == expected


def test_from_nonreactive_insert_event():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items}}[{{name}}]{{/from}}{{#reactive off}}{{#insert into items(name) values ('c')}}",
    )
    result = r.render("/m")
    import hashlib

    h1 = base64.b64encode(hashlib.sha256(repr((1, "a",)).encode()).digest())[:8].decode()
    h2 = base64.b64encode(hashlib.sha256(repr((2, "b",)).encode()).digest())[:8].decode()
    h3 = base64.b64encode(hashlib.sha256(repr((3, "c",)).encode()).digest())[:8].decode()
    expected = (
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1}')</script>[a]<script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[b]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
        f"<script>pinsert('0_{h3}',\"[c]\")</script>"
    )
    assert result.body == expected

def test_if_inside_from():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE todos(id INTEGER PRIMARY KEY, text TEXT)")
    r.db.executemany("INSERT INTO todos(id, text) VALUES (?, ?)", [(1, "a"), (2, "b")])
    snippet = (
        "{{#from todos ORDER BY id}}"
        "\n      <li>\n          <input class=\"toggle\" type=\"checkbox\" {{#if 1}}checked{{/if}}>\n      text\n      </li>\n    {{/from}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<li>\n          <input class=\"toggle\" type=\"checkbox\" checked>\n      text\n      </li>\n"
        "<li>\n          <input class=\"toggle\" type=\"checkbox\" checked>\n      text\n      </li>\n"
    )
    assert result.body == expected


def test_reactive_if_update():
    r = PageQL(":memory:")
    snippet = "{{#reactive on}}{{#set a 1}}{{#if :a}}T{{#else}}F{{/if}}{{#set a 0}}{{#set a 1}}"
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        f"<script>pstart(0)</script>T<script>pend(0)</script>"
        f"<script>pset(0,\"F\")</script>"
        f"<script>pset(0,\"T\")</script>"
    )
    assert result.body == expected


def test_reactive_if_elif_chain():
    r = PageQL(":memory:")
    snippet = (
        "{{#reactive on}}"
        "{{#set a 1}}"
        "{{#if :a == 1}}A{{#elif :a == 2}}B{{#else}}C{{/if}}"
        "{{#set a 2}}"
        "{{#set a 3}}"
        "{{#set a 1}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        f"<script>pstart(0)</script>A<script>pend(0)</script>"
        f"<script>pset(0,\"C\")</script>"
        f"<script>pset(0,\"B\")</script>"
        f"<script>pset(0,\"C\")</script>"
        f"<script>pset(0,\"A\")</script>"
    )
    assert result.body == expected


def test_reactive_if_table_dependency():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table items(value INTEGER)}}"
        "{{#insert into items(value) values (1)}}"
        "{{#reactive on}}"
        "{{#if count(*) from items}}Y{{#else}}N{{/if}}"
        "{{#delete from items}}"
        "{{#insert into items(value) values (2)}}"
        "{{#delete from items}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        f"<script>pstart(0)</script>Y<script>pend(0)</script>"
        f"<script>pset(0,\"N\")</script>"
        f"<script>pset(0,\"Y\")</script>"
        f"<script>pset(0,\"N\")</script>"
    )
    assert result.body == expected


def test_reactive_if_variable_and_table_dependency():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table items(value INTEGER)}}"
        "{{#reactive on}}"
        "{{#set threshold 1}}"
        "{{#insert into items(value) values (1)}}"
        "{{#if (select count(*) from items) > :threshold}}MORE{{#else}}LESS{{/if}}"
        "{{#set threshold 0}}"
        "{{#insert into items(value) values (2)}}"
        "{{#delete from items}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        f"<script>pstart(0)</script>LESS<script>pend(0)</script>"
        f"<script>pset(0,\"MORE\")</script>"
        f"<script>pset(0,\"LESS\")</script>"
        f"<script>pset(0,\"LESS\")</script>"
    )
    assert result.body == expected


def test_reactiveelement_adds_pparent_script():
    r = PageQL(":memory:")
    r.load_module("m", "{{#reactive on}}<div {{#if 1}}class='x'{{/if}}></div>")
    result = r.render("/m")
    assert result.body == "<div class='x'><script>pparent(0)</script></div>"


def test_reactiveelement_nonreactive_no_script():
    r = PageQL(":memory:")
    r.load_module("m", "<div {{#if 1}}class='x'{{/if}}></div>")
    result = r.render("/m")
    assert result.body == "<div class='x'></div>"

def test_reactiveelement_updates_node():
    r = PageQL(":memory:")
    snippet = (
        "{{#reactive on}}"
        "{{#set c 1}}"
        "<div {{#if :c}}class='x'{{#else}}class='y'{{/if}}></div>"
        "{{#set c 0}}"
        "{{#set c 1}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<div class='x'><script>pparent(0)</script></div>"
        "<script>pupdatetag(window.pageqlMarkers[0],\"<div class='y'></div>\")</script>"
        "<script>pupdatetag(window.pageqlMarkers[0],\"<div class='x'></div>\")</script>"
    )
    assert result.body == expected

def test_pupdatetag_in_base_script():
    from pageql.pageqlapp import base_script
    assert 'function pupdatetag' in base_script
    assert 'function pupdatenode' not in base_script

def test_pupdate_reregisters_htmx():
    from pageql.pageqlapp import base_script
    assert 'htmx.process' in base_script
