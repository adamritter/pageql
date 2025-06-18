import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

import pytest
import sqlglot


@pytest.mark.xfail(reason="sqlglot drops column list from CTE alias")
def test_cte_alias_with_column_list_preserved():
    sql = (
        "WITH RECURSIVE numbers(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM numbers WHERE n < 3) "
        "SELECT n FROM numbers"
    )
    expr = sqlglot.parse_one(sql, read="sqlite")
    assert "numbers(n)" in expr.sql(dialect="sqlite")

