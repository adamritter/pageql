import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies
from pageql.pageql import PageQL
import pytest


def test_fetch_directive_parsed():
    tokens = tokenize("{{#fetch file from 'http://ex'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'"))]


def test_fetch_directive_dependencies():
    tokens = tokenize("{{#fetch dst from :url}}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"url"}


def test_fetch_directive_render():
    seen = []

    def fetch(url: str):
        seen.append(url)
        return {"a": "1", "b": "2"}

    r = PageQL(":memory:", fetch_cb=fetch)
    r.load_module("m", "{{#fetch data from 'http://x'}}{{data__a}} {{data__b}}")
    out = r.render("/m", reactive=False).body
    assert out.strip() == "1 2"
    assert seen == ["http://x"]


def test_fetch_directive_missing_cb_errors():
    r = PageQL(":memory:")
    r.load_module("m", "{{#fetch f from 'u'}}")
    with pytest.raises(ValueError):
        r.render("/m", reactive=False)

