import sqlglot
from sqlglot import expressions as exp
from collections import Counter
from .reactive import Tables, ReactiveTable, Select, Where, Union, UnionAll, CountAll


class Fallback:
    """Fallback reactive component for unsupported SQL queries."""

    def __init__(self, sql: str, tables: Tables):
        self.sql = sql
        self.tables = tables
        self.conn = tables.conn
        self.listeners = []
        cursor = self.conn.execute(f"SELECT * FROM ({self.sql}) LIMIT 0")
        self.columns = [c[0] for c in cursor.description]
        self.rows = [tuple(row) for row in self.conn.execute(self.sql).fetchall()]

        expr = sqlglot.parse_one(sql)
        table_names = {t.name for t in expr.find_all(exp.Table)}
        for name in table_names:
            tables._get(name).listeners.append(self._on_event)

    def _emit(self, event):
        for listener in self.listeners:
            listener(event)

    def _on_event(self, _):
        new_rows = [tuple(row) for row in self.conn.execute(self.sql).fetchall()]

        old_counts = Counter(self.rows)
        new_counts = Counter(new_rows)

        for row, cnt in new_counts.items():
            old = old_counts.get(row, 0)
            if cnt > old:
                for _ in range(cnt - old):
                    self._emit([1, row])

        for row, cnt in old_counts.items():
            new = new_counts.get(row, 0)
            if cnt > new:
                for _ in range(cnt - new):
                    self._emit([2, row])

        self.rows = new_rows


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
        if expr.args.get("joins"):
            raise NotImplementedError("JOIN not supported")
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
    try:
        return build_reactive(expr, tables)
    except NotImplementedError:
        return Fallback(sql, tables)

