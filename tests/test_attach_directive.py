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


def test_attach_directive_reuse_same_file(tmp_path):
    db = tmp_path / "a.db"
    sqlite3.connect(db).close()

    r = PageQL(":memory:")
    r.load_module("m", "{%attach database :p as other%}")
    r.render("/m", {"p": str(db)}, reactive=False)
    r.render("/m", {"p": str(db)}, reactive=False)
    assert r._attached["other"] == str(db)


def test_attach_directive_switch_file(tmp_path):
    db1 = tmp_path / "a.db"
    db2 = tmp_path / "b.db"
    conn1 = sqlite3.connect(db1)
    conn1.execute("create table t(x int)")
    conn1.execute("insert into t values (1)")
    conn1.commit(); conn1.close()
    conn2 = sqlite3.connect(db2)
    conn2.execute("create table t(x int)")
    conn2.execute("insert into t values (1)")
    conn2.execute("insert into t values (2)")
    conn2.commit(); conn2.close()

    r = PageQL(":memory:")
    r.load_module("m", "{%attach database :p as other%}{{count(*) from other.t}}")
    out1 = r.render("/m", {"p": str(db1)}, reactive=False).body.strip()
    out2 = r.render("/m", {"p": str(db2)}, reactive=False).body.strip()
    assert out1 == "1"
    assert out2 == "2"
    assert r._attached["other"] == str(db2)

