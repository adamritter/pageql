import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import add_reactive_elements


def test_wrap_simple_element():
    nodes = [("text", "<div"), ("text", ">hi</div>")]
    assert add_reactive_elements(nodes) == [["#reactiveelement", nodes]]


def test_no_wrap_when_closed_in_same_node():
    nodes = [("text", "<div>hi</div>")]
    assert add_reactive_elements(nodes) == nodes


def test_entities_are_tracked():
    nodes = [("text", "&lt;span"), ("text", "&gt;ok&lt;/span&gt;")]
    assert add_reactive_elements(nodes) == [["#reactiveelement", nodes]]


def test_wrap_across_directive():
    nodes = [
        ("text", "<div"),
        ["#if", "cond", [("text", "class='x'")], []],
        ("text", ">x</div>")
    ]
    res = add_reactive_elements(nodes)
    assert res == [["#reactiveelement", [nodes[0], nodes[1], nodes[2]]]]


def test_wrap_with_directive_and_surrounding_text():
    nodes = [
        ("text", "hello "),
        ("text", "<input "),
        ["#if", "a", [("text", "checked")], []],
        ("text", "type='submit'>"),
        ("text", " world"),
    ]
    res = add_reactive_elements(nodes)
    assert res == [
        nodes[0],
        ["#reactiveelement", [nodes[1], nodes[2], nodes[3]]],
        nodes[4],
    ]
