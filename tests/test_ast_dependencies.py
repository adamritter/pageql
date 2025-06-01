import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies


def test_basic_ast_dependencies():
    snippet = (
        "{{#let cnt count(*) from nums where value > :limit}}"
        "{{#if :flag}}ok{{#else}}no{{/if}}"
        "{{#from items where id=:item_id}}{{/from}}"
    )
    tokens = tokenize(snippet)
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"limit", "flag", "item_id"}


def test_partial_ast_dependencies():
    snippet = "{{#partial sub}} {{count(*) from nums where id=:pid}} {{/partial}}"
    tokens = tokenize(snippet)
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"pid"}
