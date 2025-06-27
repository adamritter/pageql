import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL, RenderContext, _row_hash
from pageql.reactive import DerivedSignal


def test_render_nonexistent_returns_404():
    r = PageQL(":memory:")
    result = r.render("/nonexistent")
    assert result.status_code == 404


def test_rendercontext_stops_rendering_and_collects_scripts():
    r = PageQL(":memory:")
    r.load_module("m", "hello")
    result = r.render("/m", reactive=False)
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
        "<script>pstart(0)</script>True"
        "<script>pend(0)</script> "
        "<script>pstart(1)</script>True"
        "<script>pend(1)</script> False"
    )
    assert result.body == expected


def test_reactive_count_with_param_dependency():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table nums(value INTEGER)}}"
        "{{#insert into nums(value) values (1)}}"
        "{{#insert into nums(value) values (2)}}"
        "{{#insert into nums(value) values (3)}}"
        "{{#create table vars(val INTEGER)}}"
        "{{#insert into vars(val) values (1)}}"
        "{{#reactive on}}"
        "{{#let a = (select val from vars)}}"
        "{{#let cnt = count(*) from nums where value > :a}}"
        "{{cnt}}"
        "{{#update vars set val = 2}}"
        "{{#delete from nums where value = 3}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m", reactive=False)
    expected = (
        ""
        "<script>pstart(0)</script>2<script>pend(0)</script>"
        "<script>pset(0,\"1\")</script>"
        "<script>pset(0,\"0\")</script>"
    )
    assert result.body == expected


def test_render_derived_signal_value_and_eval():
    r = PageQL(":memory:")
    sig = DerivedSignal(lambda: 1, [])
    r.load_module("m", "{{foo}} {{:foo + :foo}}")
    result = r.render("/m", {"foo": sig}, reactive=False)
    assert result.body.strip() == "1 2"


def test_from_reactive_uses_parse(monkeypatch):
    import pageql.reactive_sql as rsql

    seen = []
    original = rsql.parse_reactive

    def wrapper(expr, tables, params=None, **kwargs):
        seen.append(expr.sql(dialect="sqlite"))
        return original(expr, tables, params, **kwargs)

    monkeypatch.setattr(rsql, "parse_reactive", wrapper)
    import pageql.database as pdb
    monkeypatch.setattr(pdb, "parse_reactive", wrapper)
    import pageql.pageql as pql
    monkeypatch.setattr(pql, "parse_reactive", wrapper)

    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    r.load_module("m", "{{#reactive on}}{{#from items}}[{{id}}]{{/from}}")
    result = r.render("/m", reactive=False)
    assert seen == ["SELECT * FROM items"]
    h1 = _row_hash((1, "a"))
    h2 = _row_hash((2, "b"))
    expected = (
        ""
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1}')</script>[1]<script>pend('0_{h1}')</script>\n"
        f"<script>pstart('0_{h2}')</script>[2]<script>pend('0_{h2}')</script>\n"
        f"<script>pend(0)</script>"
    )
    assert result.body == expected


def test_from_reactive_caches_queries(monkeypatch):
    import pageql.reactive_sql as rsql

    seen = []
    original = rsql.parse_reactive

    def wrapper(expr, tables, params=None, **kwargs):
        seen.append(expr.sql(dialect="sqlite"))
        return original(expr, tables, params, **kwargs)

    monkeypatch.setattr(rsql, "parse_reactive", wrapper)
    import pageql.database as pdb
    monkeypatch.setattr(pdb, "parse_reactive", wrapper)
    import pageql.pageql as pql
    monkeypatch.setattr(pql, "parse_reactive", wrapper)

    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    snippet = (
        "{{#reactive on}}"
        "{{#let v = 1}}"
        "{{#from items where id=:v}}[{{id}}]{{/from}}"
        "{{#from items where id=:v}}[{{id}}]{{/from}}"
    )
    r.load_module("m", snippet)
    r.render("/m")
    assert seen.count("SELECT * FROM items WHERE id = :v") == 1


def test_randomblob_expression_not_cached(monkeypatch):
    import pageql.reactive_sql as rsql

    seen = []
    original = rsql.parse_reactive

    def wrapper(expr, tables, params=None, **kwargs):
        seen.append(expr.sql(dialect="sqlite"))
        return original(expr, tables, params, **kwargs)

    monkeypatch.setattr(rsql, "parse_reactive", wrapper)
    import pageql.database as pdb
    monkeypatch.setattr(pdb, "parse_reactive", wrapper)
    import pageql.pageql as pql
    monkeypatch.setattr(pql, "parse_reactive", wrapper)

    r = PageQL(":memory:")
    snippet = (
        "{{#reactive on}}"
        "{{#let t1 = lower(hex(randomblob(4)))}}"
        "{{#let t2 = lower(hex(randomblob(4)))}}"
    )
    r.load_module("m", snippet)
    r.render("/m")
    assert seen.count("SELECT LOWER(HEX(RANDOMBLOB(4)))") == 2


def test_from_reactive_reparses_after_cleanup(monkeypatch):
    import pageql.reactive_sql as rsql

    seen = []
    original = rsql.parse_reactive

    def wrapper(expr, tables, params=None, **kwargs):
        seen.append(expr.sql(dialect="sqlite"))
        return original(expr, tables, params, **kwargs)

    monkeypatch.setattr(rsql, "parse_reactive", wrapper)
    import pageql.database as pdb
    monkeypatch.setattr(pdb, "parse_reactive", wrapper)
    import pageql.pageql as pql
    monkeypatch.setattr(pql, "parse_reactive", wrapper)

    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    snippet = (
        "{{#reactive on}}"
        "{{#from items}}[{{id}}]{{/from}}"
        "{{#reactive off}}"
    )
    r.load_module("m", snippet)

    r.render("/m")
    assert seen.count("SELECT * FROM items") == 1
    r.render("/m")
    assert seen.count("SELECT * FROM items") == 2




def test_reactive_set_comments():
    snippet = """{{#reactive on}}
{{#create table vals(name TEXT, value INTEGER)}}
{{#insert into vals(name, value) values ('a', 1)}}
{{#insert into vals(name, value) values ('b', 3)}}
{{#let a = (select value from vals where name = 'a')}}
{{a}}
{{:a + :a}}
{{#let b = (select value from vals where name = 'b')}}
<p>{{:a + :b}} = 4</p>
{{#let c = :a+:b}}
<p>{{:c}} = c = 4</p>
{{#update vals set value = 2 where name = 'a'}}
<p>{{:a + :b}} = 5</p>
<p>{{:c}} = c = 5</p>
{{#reactive off}}"""

    r = PageQL(":memory:")
    r.load_module("m", snippet)
    result = r.render("/m", reactive=False)
    expected = (
        "\n\n\n"
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
    result = r.render("/m", reactive=False)
    h1 = _row_hash((1, "a"))
    h2 = _row_hash((2, "b"))
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
    result = r.render("/m", reactive=False)

    h1_old = _row_hash((1, "a"))
    h1_new = _row_hash((1, "c"))
    h2 = _row_hash((2, "b"))
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
    result = r.render("/m", reactive=False)

    h1 = _row_hash((1, "a"))
    h2 = _row_hash((2, "b"))
    h3 = _row_hash((3, "c"))
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

    h1 = _row_hash((1, "a"))
    h2 = _row_hash((2, "b"))
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

    h1_old = _row_hash((1, "a"))
    h1_new = _row_hash((1, "c"))
    h2 = _row_hash((2, "b"))
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

    h1 = _row_hash((1, "a"))
    h2 = _row_hash((2, "b"))
    h3 = _row_hash((3, "c"))
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
    result = r.render("/m", reactive=False)
    expected = (
        "<li>\n          <input class=\"toggle\" type=\"checkbox\" checked>\n      text\n      </li>\n"
        "<li>\n          <input class=\"toggle\" type=\"checkbox\" checked>\n      text\n      </li>\n"
    )
    assert result.body == expected


def test_reactive_if_update():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table vals(name TEXT, value INTEGER)}}"
        "{{#insert into vals(name, value) values ('a', 1)}}"
        "{{#reactive on}}{{#let a = value from vals where name = 'a'}}{{#if :a}}T{{#else}}F{{/if}}{{#update vals set value = 0 where name = 'a'}}{{#update vals set value = 1 where name = 'a'}}"
    )
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
    r.db.execute("CREATE TABLE vals(name TEXT, value INTEGER)")
    r.db.executemany("INSERT INTO vals(name, value) VALUES (?, ?)", [("a", 1)])
    snippet = (
        "{{#reactive on}}"
        "{{#let a = value from vals where name = 'a'}}"
        "{{#if :a == 1}}A{{#elif :a == 2}}B{{#else}}C{{/if}}"
        "{{#update vals set value = 2 where name = 'a'}}"
        "{{#update vals set value = 3 where name = 'a'}}"
        "{{#update vals set value = 1 where name = 'a'}}"
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
        "{{#create table vals(name TEXT, value INTEGER)}}"
        "{{#insert into vals(name, value) values ('threshold', 1)}}"
        "{{#reactive on}}"
        "{{#let threshold = value from vals where name = 'threshold'}}"
        "{{#insert into items(value) values (1)}}"
        "{{#if (select count(*) from items) > :threshold}}MORE{{#else}}LESS{{/if}}"
        "{{#update vals set value = 0 where name = 'threshold'}}"
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


def test_reactiveelement_adds_pprevioustag_script():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE vals(name TEXT, value INTEGER)")
    r.db.executemany("INSERT INTO vals(name, value) VALUES (?, ?)", [("c", 1)])
    snippet = (
        "{{#reactive on}}"
        "{{#let c = value from vals where name = 'c'}}"
        "<div {{#if :c}}class='x'{{/if}}></div>"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    assert result.body == "<div class='x'><script>pprevioustag(0)</script></div>"


def test_reactiveelement_constant_no_script():
    r = PageQL(":memory:")
    r.load_module("m", "{{#reactive on}}<div {{#if 1}}class='x'{{/if}}></div>")
    result = r.render("/m")
    assert result.body == "<div class='x'></div>"


def test_reactiveelement_nonreactive_no_script():
    r = PageQL(":memory:")
    r.load_module("m", "<div {{#if 1}}class='x'{{/if}}></div>")
    result = r.render("/m", reactive=False)
    assert result.body == "<div class='x'></div>"

def test_reactiveelement_updates_node():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE vals(name TEXT, value INTEGER)")
    r.db.executemany("INSERT INTO vals(name, value) VALUES (?, ?)", [("c", 1)])
    snippet = (
        "{{#reactive on}}"
        "{{#let c = value from vals where name = 'c'}}"
        "<div {{#if :c}}class='x'{{#else}}class='y'{{/if}}></div>"
        "{{#update vals set value = 0 where name = 'c'}}"
        "{{#update vals set value = 1 where name = 'c'}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<div class='x'><script>pprevioustag(0)</script></div>"
        "<script>pupdatetag(0,\"<div class='y'></div>\")</script>"
        "<script>pupdatetag(0,\"<div class='x'></div>\")</script>"
    )
    assert result.body == expected

def test_reactiveelement_input_value():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE vals(name TEXT, value INTEGER)")
    r.db.executemany("INSERT INTO vals(name, value) VALUES (?, ?)", [("c", 1)])
    snippet = (
        "{{#reactive on}}"
        "{{#let c = value from vals where name = 'c'}}"
        "<input type='text' value='{{c}}'>"
        "{{#update vals set value = 2 where name = 'c'}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<input type='text' value='1'><script>pprevioustag(0)</script>"
        "<script>pupdatetag(0,\"<input type='text' value='2'>\")</script>"
    )
    assert result.body == expected


def test_reactiveelement_self_closing_input():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table vals(name TEXT, value INTEGER)}}"
        "{{#insert into vals(name, value) values ('c', 1)}}"
        "{{#reactive on}}"
        "{{#let c = value from vals where name = 'c'}}"
        "<input type='text' value='{{c}}' />"
        "{{#update vals set value = 2 where name = 'c'}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<input type='text' value='1' /><script>pprevioustag(0)</script>"
        "<script>pupdatetag(0,\"<input type='text' value='2' />\")</script>"
    )
    assert result.body == expected

def test_reactiveelement_if_with_table_insert_updates_input():
    r = PageQL(":memory:")
    r.db.execute(
        "CREATE TABLE todos(id INTEGER PRIMARY KEY, text TEXT, completed INTEGER)"
    )
    snippet = (
        "{{#reactive on}}"
        "{{#let active_count = count(*) from todos}}"
        "<p>Active count is 1: <input type='checkbox' {{#if :active_count == 1}}checked{{/if}}></p>"
        "{{#insert into todos(text, completed) values ('test', 0)}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<p>Active count is 1: <input type='checkbox' ><script>pprevioustag(0)</script></p>"
        "<script>pupdatetag(0,\"<input type='checkbox' checked>\")</script>"
    )
    assert result.body == expected


def test_reactiveelement_if_variable_updates_checked():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table vals(name TEXT, value INTEGER)}}"
        "{{#insert into vals(name, value) values ('flag', 1)}}"
        "{{#reactive on}}"
        "{{#let flag = value from vals where name = 'flag'}}"
        "<input type='checkbox' {{#if :flag}}checked{{/if}}>"
        "{{#update vals set value = 0 where name = 'flag'}}"
        "{{#update vals set value = 1 where name = 'flag'}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<input type='checkbox' checked><script>pprevioustag(0)</script>"
        "<script>pupdatetag(0,\"<input type='checkbox' >\")</script>"
        "<script>pupdatetag(0,\"<input type='checkbox' checked>\")</script>"
    )
    assert result.body == expected


def test_reactiveelement_delete_and_insert_updates_input_and_text():
    r = PageQL(":memory:")
    r.db.execute(
        "CREATE TABLE todos(id INTEGER PRIMARY KEY, text TEXT, completed INTEGER)"
    )
    snippet = (
        "{{#reactive on}}"
        "{{#delete from todos where completed = 0}}"
        "{{#let active_count = COUNT(*) from todos WHERE completed = 0}}"
        '<p><input class="toggle{{3}}" type="checkbox" {{#if 1}}checked{{/if}}><input type="text" value="{{active_count}}"></p>'
        "{{#insert into todos(text, completed) values ('test', 0)}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<p><input class=\"toggle3\" type=\"checkbox\" checked><input type=\"text\" value=\"0\"><script>pprevioustag(0)</script></p>"
        "<script>pupdatetag(0,\"<input type=\\\"text\\\" value=\\\"1\\\">\")</script>"
    )
    assert result.body == expected


def test_reactive_text_updates_with_table_count():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table items(value INTEGER)}}"
        "{{#reactive on}}"
        "<p>Count: {{count(*) from items}}</p>"
        "{{#insert into items(value) values (1)}}"
        "{{#delete from items}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "<p>Count: <script>pstart(0)</script>0<script>pend(0)</script></p>"
        "<script>pset(0,\"1\")</script>"
        "<script>pset(0,\"0\")</script>"
    )
    assert result.body == expected

def test_pupdatetag_in_base_script():
    from pageql.client_script import client_script
    script = client_script("cid")
    assert 'function pupdatetag' in script
    assert 'function pupdatenode' not in script

def test_pupdate_reregisters_htmx():
    from pageql.client_script import client_script
    script = client_script("cid")
    assert 'htmx.process' in script

def test_pinsert_reregisters_htmx():
    from pageql.client_script import client_script
    script = client_script("cid")
    idx = script.find('function pinsert')
    assert idx != -1
    assert script.find('htmx.process', idx) != -1


def test_client_script_get_body_function():
    from pageql.client_script import client_script
    script = client_script("cid")
    assert 'getBodyTextContent' in script
    assert 'get body text content' in script


def test_porderupdate_in_base_script():
    from pageql.client_script import client_script
    script = client_script("cid")
    assert 'function porderupdate' in script


def test_order_functions_in_base_script():
    from pageql.client_script import client_script
    script = client_script("cid")
    assert 'function orderdelete' in script
    assert 'function orderinsert' in script
    assert 'function orderupdate' in script


def test_pinsert_escapes_script_tag():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE todos(id INTEGER PRIMARY KEY, completed INTEGER)")
    r.db.executemany("INSERT INTO todos(completed) VALUES (?)", [(0,), (1,)])
    snippet = (
        "{{#reactive on}}"
        "{{#from todos}}<li><input type='checkbox' {{#if completed}}checked{{/if}}><script>hi()</script></li>{{/from}}"
        "{{#insert into todos(completed) values (0)}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    assert "pinsert" in result.body
    assert "<\\/script>" in result.body


def test_pinsert_does_not_send_marker_scripts():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value INTEGER)")
    snippet = (
        "{{#reactive on}}"
        "{{#from items}}<li>{{#let a = 1}}{{#if :a}}X{{/if}}</li>{{/from}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    ctx = result.context
    assert ctx.scripts == []

    r.tables.executeone("INSERT INTO items(value) VALUES (1)", {})

    assert len(ctx.scripts) == 1
    sc = ctx.scripts[0]
    assert sc.startswith("pinsert(")
    assert "pstart" not in sc and "pend" not in sc


def test_let_null_literal():
    r = PageQL(":memory:")
    snippet = (
        "{{#let v = NULL}}"
        "{{#if :v IS NULL}}null{{#else}}not null{{/if}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    assert "null" in result.body

def test_nested_if_reactive_bug():
    r = PageQL(":memory:")
    snippet = (
        "{{#create table if not exists todos (id integer primary key autoincrement, text text)}}\n"
        "{{#delete from todos}}\n"
        "{{#insert into todos (text) values ('Hello, world!')}}\n"
        "{{#let todos_count = (select count(*) from todos)}}\n"
        "{{todos_count}}\n"
        "{{#if :todos_count > 1}}\n"
        "greater than 1\n"
        "{{#if :todos_count > 2}}\n"
        "greater than 2\n"
        "{{#else}}\n"
        "less or equal to 2\n"
        "{{/if}}\n"
        "{{#else}}\n"
        "less or equal to 1\n"
        "{{/if}}\n"
        "\n"
        "{{#insert into todos (text) values ('Hello, world!')}}\n"
        "{{#insert into todos (text) values ('Hello, world!')}}"
    )
    r.load_module("m", snippet)
    result = r.render("/m")
    expected = (
        "\n\n<script>pstart(0)</script>1<script>pend(0)</script>\n"
        "<script>pstart(1)</script>\n"
        "less or equal to 1\n"
        "<script>pend(1)</script>\n"
        "<script>pset(0,\"2\")</script><script>pset(1,\"greater than 1\\n<script>pstart(2)<\\/script>\\nless or equal to 2\\n<script>pend(2)<\\/script>\")</script>\n"
        "<script>pset(0,\"3\")</script><script>pset(2,\"greater than 2\")</script>"
    )
    assert result.body == expected


def test_order_by_update_reorders_rows():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, text TEXT)")
    r.db.executemany("INSERT INTO items(text) VALUES (?)", [("b",), ("a",)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items ORDER BY text}}[{{id}}:{{text}}]{{/from}}{{#update items set text='c' where id=2}}",
    )
    result = r.render("/m", reactive=False)

    expected = (
        f"<script>pstart(0)</script>"
        f"<script>pstart(1)</script>[2:a]<script>pend(1)</script>\n"
        f"<script>pstart(1)</script>[1:b]<script>pend(1)</script>\n"
        f"<script>pend(0)</script>"
        f"<script>orderupdate(1,0,1,\"[2:c]\")</script>"
        f"<script>porderupdate(1,0,1)</script>"
    )
    assert result.body == expected


def test_order_by_update_with_limit_reorders_rows():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, val INTEGER)")
    r.db.executemany("INSERT INTO items(val) VALUES (?)", [(1,), (2,), (3,)])
    r.load_module(
        "m",
        "{{#reactive on}}{{#from items ORDER BY val LIMIT 2}}[{{id}}:{{val}}]{{/from}}{{#update items set val=0 where id=3}}",
    )
    result = r.render("/m", reactive=False)

    expected = (
        f"<script>pstart(0)</script>"
        f"<script>pstart(1)</script>[1:1]<script>pend(1)</script>\n"
        f"<script>pstart(1)</script>[2:2]<script>pend(1)</script>\n"
        f"<script>pend(0)</script>"
        f"<script>orderinsert(1,0,\"[3:0]\")</script>"
        f"<script>orderdelete(1,2)</script>"
    )
    assert result.body == expected
