import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast


def test_from_node_has_dependencies():
    tokens = tokenize("{{#from items where id=:x}}{{#if :y}}ok{{#endif}}{{#endfrom}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    from_node = body[0]
    assert from_node[0] == "#from"
    assert from_node[2] == {"y"}
