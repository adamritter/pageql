import sqlglot
from sqlglot import expressions as exp
from .reactive import Tables, ReactiveTable, Select, Where, Union, UnionAll, CountAll


def build_reactive(expr, tables: Tables):
    if isinstance(expr, exp.Subquery):
        return build_reactive(expr.this, tables)
    if isinstance(expr, exp.Union):
        left = build_reactive(expr.this, tables)
        right = build_reactive(expr.expression, tables)
        if expr.args.get("distinct", True):
            return Union(left, right)
        return UnionAll(left, right)
    if isinstance(expr, exp.Select):
        from_expr = expr.args.get("from")
        if from_expr is None:
            raise ValueError("SELECT missing FROM clause")
        parent = build_from(from_expr.this, tables)
        if expr.args.get("where"):
            parent = Where(parent, expr.args["where"].this.sql())
        select_list = expr.args.get("expressions") or [exp.Star()]
        if len(select_list) == 1:
            col = select_list[0]
            if isinstance(col, exp.Star):
                return parent
            if isinstance(col, exp.Count) and isinstance(col.this, exp.Star):
                return CountAll(parent)
        select_sql = ", ".join(col.sql() for col in select_list)
        return Select(parent, select_sql)
    if isinstance(expr, exp.Table):
        return tables._get(expr.name)
    raise NotImplementedError(f"Unsupported expression type: {type(expr)}")


def build_from(expr, tables: Tables):
    if isinstance(expr, exp.Table):
        return tables._get(expr.name)
    if isinstance(expr, (exp.Select, exp.Union, exp.Subquery)):
        return build_reactive(expr, tables)
    raise NotImplementedError(f"Unsupported FROM expression: {type(expr)}")


def parse_reactive(sql: str, tables: Tables):
    """Parse a SQL SELECT into reactive components."""
    expr = sqlglot.parse_one(sql)
    return build_reactive(expr, tables)
