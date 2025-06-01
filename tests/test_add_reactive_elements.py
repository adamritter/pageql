import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

import sqlglot
from pageql.parser import add_reactive_elements, tokenize, build_ast


def test_wrap_simple_element():
    nodes = [("text", "<div"), ("text", ">hi</div>")]
    assert add_reactive_elements(nodes) == [("text", "<div"), ("text", ">hi</div>")]


def test_no_wrap_when_closed_in_same_node():
    nodes = [("text", "<div>hi</div>")]
    assert add_reactive_elements(nodes) == nodes


def test_wrap_across_directive():
    nodes = [
        ("text", "<div"),
        ["#if", ("cond", sqlglot.parse_one("SELECT cond", read="sqlite")), [("text", "class='x'")], []],
        ("text", ">x</div>")
    ]
    res = add_reactive_elements(nodes)
    assert res == [
        ["#reactiveelement", [
            ("text", "<div"),
            ["#if", ("cond", sqlglot.parse_one("SELECT cond", read="sqlite")), [("text", "class='x'")], []],
            ("text", ">")
        ]],
        ("text", "x</div>")
    ]


def test_wrap_with_directive_and_surrounding_text():
    nodes = [
        ("text", "hello <input "),
        ["#if", ("a", sqlglot.parse_one("SELECT a", read="sqlite")), [("text", "checked")], []],
        ("text", "type='submit'> world"),
    ]
    res = add_reactive_elements(nodes)
    assert res == [
        ("text", "hello "),
        ["#reactiveelement", [
            ("text", "<input "),
            ["#if", ("a", sqlglot.parse_one("SELECT a", read="sqlite")), [("text", "checked")], []],
            ("text", "type='submit'>"),
        ]],
        ("text", " world"),
    ]


def test_input_if_inside_paragraph():
    nodes = [
        ("text", "<p>Active count is 1: <input type='checkbox' "),
        ["#if", (":active_count == 1", sqlglot.parse_one("SELECT :active_count == 1", read="sqlite")), [("text", "checked")]],
        ("text", "></p>")
    ]
    res = add_reactive_elements(nodes)
    assert res == [
        ("text", "<p>Active count is 1: "),
        ["#reactiveelement", [
            ("text", "<input type='checkbox' "),
            ["#if", (":active_count == 1", sqlglot.parse_one("SELECT :active_count == 1", read="sqlite")), [("text", "checked")]],
            ("text", ">")
        ]],
        ("text", "</p>")
    ]


def test_delete_insert_input_and_text():
    snippet = (
        "{{#reactive on}}"
        "{{#delete from todos where completed = 0}}"
        "{{#let active_count = COUNT(*) from todos WHERE completed = 0}}"
        '<p><input class="toggle{{3}}" type="checkbox" {{#if 1}}checked{{/if}}>'
        '<input type="text" value="{{active_count}}"></p>'
        "{{#insert into todos(text, completed) values ('test', 0)}}"
    )
    tokens = tokenize(snippet)
    body, _ = build_ast(tokens, dialect="sqlite")
    res = add_reactive_elements(body)
    assert res[0] == ("#reactive", "on")
    assert res[1] == ("#delete", "from todos where completed = 0")
    assert res[2][0] == "#let"
    assert res[2][1][0] == "active_count"
    assert res[2][1][1] == "COUNT(*) from todos WHERE completed = 0"
    assert res[2][1][2].sql(dialect="sqlite") == sqlglot.parse_one(
        "SELECT COUNT(*) from todos WHERE completed = 0", read="sqlite"
    ).sql(dialect="sqlite")
    assert res[3:] == [
        ("text", "<p>"),
        [
            "#reactiveelement",
            [
                ("text", "<input class=\"toggle"),
                ("render_expression", "3"),
                ("text", "\" type=\"checkbox\" "),
                ["#if", ("1", sqlglot.parse_one("SELECT 1", read="sqlite")), [("text", "checked")]],
                ("text", ">"),
            ],
        ],
        [
            "#reactiveelement",
            [
                ("text", "<input type=\"text\" value=\""),
                ("render_param", "active_count"),
                ("text", "\">")
            ],
        ],
        ("text", "</p>"),
        ("#insert", "into todos(text, completed) values ('test', 0)"),
    ]


def test_wrap_inside_else_branch():
    snippet = (
        "<div>{{#if 1}}<span>hi</span>{{#else}}<input value='{{x}}'>{{/if}}</div>"
    )
    tokens = tokenize(snippet)
    body, _ = build_ast(tokens, dialect="sqlite")
    res = add_reactive_elements(body)
    assert res == [
        ("text", "<div>"),
        [
            "#if",
            ("1", sqlglot.parse_one("SELECT 1", read="sqlite")),
            [("text", "<span>hi</span>")],
            [
                [
                    "#reactiveelement",
                    [
                        ("text", "<input value='"),
                        ("render_param", "x"),
                        ("text", "'>"),
                    ],
                ]
            ],
        ],
        ("text", "</div>"),
    ]
