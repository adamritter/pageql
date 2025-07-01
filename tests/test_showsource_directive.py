import sys, types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *a, **k: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast
from pageql.pageql import PageQL
from pageql.highlighter import highlight_block


def test_showsource_directive_parses():
    tokens = tokenize("{%showsource%}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#showsource", None)]


def test_showsource_outputs_highlighted_source():
    r = PageQL(":memory:")
    src = "hi\n{%showsource%}"
    r.load_module("m", src)
    result = r.render("/m", reactive=False)
    assert result.body == "hi\n" + highlight_block(src)
