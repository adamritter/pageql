import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import add_reactive_elements


def test_wrap_simple_element():
    nodes = [("text", "<div"), ("text", ">hi</div>")]
    assert add_reactive_elements(nodes) == [("text", "<div"), ("text", ">hi</div>")]


def test_no_wrap_when_closed_in_same_node():
    nodes = [("text", "<div>hi</div>")]
    assert add_reactive_elements(nodes) == nodes


def test_wrap_across_directive():
    nodes = [
        ("text", "<div"),
        ["#if", "cond", [("text", "class='x'")], []],
        ("text", ">x</div>")
    ]
    res = add_reactive_elements(nodes)
    assert res == [
        ["#reactiveelement", [
            ("text", "<div"),
            ["#if", "cond", [("text", "class='x'")], []],
            ("text", ">")
        ]],
        ("text", "x</div>")
    ]


def test_wrap_with_directive_and_surrounding_text():
    nodes = [
        ("text", "hello <input "),
        ["#if", "a", [("text", "checked")], []],
        ("text", "type='submit'> world"),
    ]
    res = add_reactive_elements(nodes)
    assert res == [
        ("text", "hello "),
        ["#reactiveelement", [
            ("text", "<input "),
            ["#if", "a", [("text", "checked")], []],
            ("text", "type='submit'>"),
        ]],
        ("text", " world"),
    ]


def test_input_if_inside_paragraph():
    nodes = [
        ("text", "<p>Active count is 1: <input type='checkbox' "),
        ["#if", ":active_count == 1", [("text", "checked")]],
        ("text", "></p>")
    ]
    res = add_reactive_elements(nodes)
    assert res == [
        ("text", "<p>Active count is 1: "),
        ["#reactiveelement", [
            ("text", "<input type='checkbox' "),
            ["#if", ":active_count == 1", [("text", "checked")]],
            ("text", ">")
        ]],
        ("text", "</p>")
    ]
