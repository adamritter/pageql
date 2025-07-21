import pytest
import sqlglot
from sqlglot import expressions as exp


@pytest.mark.xfail(reason="sqlglot incorrectly handles EXISTS subquery counting")
def test_findall_exists_subquery():
    sql = "select * from tweets where exists(select 1 from tweets t2 where t2.id = tweets.id)"
    expr = sqlglot.parse_one(sql, read="sqlite")
    subqueries = list(expr.find_all(exp.Subquery))
    assert len(subqueries) == 1
