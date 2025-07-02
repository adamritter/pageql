import sys
sys.path.insert(0, "src")

import sqlglot
from pageql.reactive_sql import _replace_placeholders


def test_mysql_hex_literal_placeholder():
    expr = sqlglot.parse_one("SELECT :b", read="mysql")
    _replace_placeholders(expr, {"b": b"\x33\xff"}, "mysql")
    assert expr.sql(dialect="mysql") == "SELECT 0x33ff"
