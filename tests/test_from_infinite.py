import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast


def test_from_parses_infinite_keyword():
    tokens = tokenize("{%from items infinite%}{%endfrom%}")
    body, _ = build_ast(tokens, dialect="sqlite")
    node = body[0]
    assert node[0] == "#from"
    assert node[4] is True
    assert node[1][0] == "items"
