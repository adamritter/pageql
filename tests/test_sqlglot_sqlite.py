import sqlglot
from sqlglot import expressions as exp


def test_sqlite_hex_literal_parsing():
    expr = sqlglot.parse_one("SELECT X'33'", read="sqlite")
    assert isinstance(expr, exp.Select)
    assert isinstance(expr.expressions[0], exp.HexString)
    assert expr.sql(dialect="sqlite") == "SELECT x'33'"
