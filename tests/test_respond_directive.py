import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies


def test_respond_directive_default():
    tokens = tokenize("{{#respond}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#respond", ("200", None))]


def test_respond_directive_status_and_body():
    tokens = tokenize("{{#respond 202 body='ok'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#respond", ("202", "'ok'"))]


def test_respond_directive_body_only():
    tokens = tokenize("{{#respond body='hey'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#respond", ("200", "'hey'"))]


def test_respond_directive_dependencies():
    tokens = tokenize("{{#respond :code body=:msg}}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"code", "msg"}
