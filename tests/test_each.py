import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.pageql import PageQL
from pageql.parser import tokenize, build_ast, ast_param_dependencies


def test_each_basic():
    r = PageQL(":memory:")
    r.load_module("m", "{{#each items}}[{{items}}]{{/each}}")
    params = {
        "items__count": 3,
        "items__0": "a",
        "items__1": "b",
        "items__2": "c",
    }
    result = r.render("/m", params, reactive=False)
    assert result.body == "[a]\n[b]\n[c]\n"


def test_each_ast_dependencies():
    snippet = "{{#each nums}}{{/each}}"
    tokens = tokenize(snippet)
    ast = build_ast(tokens)
    deps = ast_param_dependencies(ast)
    assert deps == {"nums__count"}
