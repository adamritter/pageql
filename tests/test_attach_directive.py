import sys
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies
from pageql.pageql import PageQL
import sqlite3


def test_attach_directive_parsed():
    tokens = tokenize("{%attach database 'file.db' as other%}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#attach", "database 'file.db' as other")]


def test_attach_directive_dependencies():
    tokens = tokenize("{%attach database :p as other%}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"p"}


def test_attach_directive_render(tmp_path):
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("create table t(x int)")
    conn.execute("insert into t values (1)")
    conn.commit()
    conn.close()

    r = PageQL(":memory:")
    r.load_module("m", "{%attach database :p as other%}{{count(*) from other.t}}")
    out = r.render("/m", {"p": str(other)}, reactive=False).body.strip()
    assert out == "1"

