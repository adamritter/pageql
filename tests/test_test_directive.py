import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast
from pageql.pageql import PageQL


def test_build_ast_collects_tests():
    tokens = tokenize("{{#test t1}}hi {{#render x}}{{#endtest}}")
    tests = {}
    body, partials = build_ast(tokens, dialect="sqlite", tests=tests)
    assert body == []
    assert partials == {}
    assert tests == {"t1": [("text", "hi "), ("#render", "x")]} 


def test_load_module_stores_tests():
    r = PageQL(":memory:")
    src = "{{#test t2}}ok{{#endtest}}"
    r.load_module("m", src)
    assert "m" in r.tests
    assert r.tests["m"] == {"t2": [("text", "ok")]}
