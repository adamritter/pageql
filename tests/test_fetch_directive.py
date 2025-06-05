import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies


def test_fetch_directive_parsed():
    tokens = tokenize("{{#fetch file from 'http://ex'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'"))]


def test_fetch_directive_dependencies():
    tokens = tokenize("{{#fetch dst from :url}}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"url"}

