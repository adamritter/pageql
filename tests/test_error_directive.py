import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

import pytest
from pageql.pageql import PageQL
from pageql.parser import tokenize, build_ast, ast_param_dependencies


def test_error_directive_raises():
    r = PageQL(":memory:")
    r.load_module("m", "{%error 'boom'%}")
    with pytest.raises(ValueError) as exc:
        r.render("/m", reactive=False)
    assert "boom" in str(exc.value)


def test_error_directive_dependencies():
    tokens = tokenize("{%error :msg%}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"msg"}
