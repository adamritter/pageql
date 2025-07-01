import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies
from pageql.pageql import PageQL


def test_respond_directive_default():
    tokens = tokenize("{%respond%}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#respond", ("200", None))]


def test_respond_directive_status_and_body():
    tokens = tokenize("{%respond 202 body='ok'%}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#respond", ("202", "'ok'"))]


def test_respond_directive_body_only():
    tokens = tokenize("{%respond body='hey'%}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#respond", ("200", "'hey'"))]


def test_respond_directive_dependencies():
    tokens = tokenize("{%respond :code body=:msg%}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"code", "msg"}


def test_respond_runtime_status_only():
    r = PageQL(":memory:")
    r.load_module("m", "a{%respond 201%}b")
    res = r.render("/m", reactive=False)
    assert res.status_code == 201
    assert res.body == "a"


def test_respond_runtime_with_body():
    r = PageQL(":memory:")
    r.load_module("m", "a{%respond 404 body='err'%}b")
    res = r.render("/m", reactive=False)
    assert res.status_code == 404
    assert res.body == "err"
