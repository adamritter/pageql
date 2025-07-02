import sys
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies


def test_header_directive_parses():
    tokens = tokenize("{%header X-Test 'v'%}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#header", ("X-Test", "'v'"))]


def test_header_directive_dependencies():
    tokens = tokenize("{%header X-Test :val%}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"val"}
