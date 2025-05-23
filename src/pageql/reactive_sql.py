import sqlglot
from sqlglot import expressions as exp
from .reactive import (
    Tables,
    ReactiveTable,
    Select,
    Where,
    Union,
    UnionAll,
    CountAll,
    DerivedSignal,
    DependentValue,
)


def _replace_placeholders(expr: exp.Expression, params: dict[str, object] | None) -> None:
    """Replace ``Placeholder`` nodes in *expr* using values from *params*."""

    if not params:
        return

    for ph in list(expr.find_all(exp.Placeholder)):
        name = ph.this
        if name not in params:
            continue
        val = params[name]
        if isinstance(val, DerivedSignal):
            val = val.value
        if isinstance(val, DependentValue):
            val = val.value
        if isinstance(val, (int, float)):
            lit = exp.Literal.number(val)
        else:
            lit = exp.Literal.string(str(val))
        ph.replace(lit)


class FallbackReactive:
    """Generic reactive component for unsupported queries."""

    def __init__(self, tables: Tables, sql: str, expr: exp.Expression | None = None):
        self.tables = tables
        self.conn = tables.conn
        self.sql = sql
        self.listeners = []

        if expr is None:
            expr = sqlglot.parse_one(sql)

        # Determine table dependencies
        self.deps = []
        for tbl in expr.find_all(exp.Table):
            dep = tables._get(tbl.name)
            self.deps.append(dep)
            dep.listeners.append(self._on_parent_event)

        cur = self.conn.execute(sql)
        self.columns = [d[0] for d in cur.description]
        self.rows = list(cur.fetchall())
        self._counts = {}
        for r in self.rows:
            self._counts[r] = self._counts.get(r, 0) + 1

    def _emit(self, event):
        for l in list(self.listeners):
            l(event)

    def _on_parent_event(self, _):
        cur = self.conn.execute(self.sql)
        rows = list(cur.fetchall())
        new_counts = {}
        for r in rows:
            new_counts[r] = new_counts.get(r, 0) + 1

        for row, cnt in new_counts.items():
            old = self._counts.get(row, 0)
            if cnt > old:
                for _ in range(cnt - old):
                    self._emit([1, row])

        for row, cnt in self._counts.items():
            new = new_counts.get(row, 0)
            if new < cnt:
                for _ in range(cnt - new):
                    self._emit([2, row])

        self.rows = rows
        self._counts = new_counts

    def remove_listener(self, listener):
        """Remove *listener* and detach from dependencies when unused."""
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            for dep in self.deps:
                if self._on_parent_event in getattr(dep, "listeners", []):
                    dep.listeners.remove(self._on_parent_event)


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
            return FallbackReactive(tables, expr.sql())
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


def parse_reactive(sql: str, tables: Tables, params: dict[str, object] | None = None):
    """Parse a SQL SELECT into reactive components.

    Placeholders in *sql* are replaced using *params* before building the
    reactive expression tree.
    """
    expr = sqlglot.parse_one(sql)
    _replace_placeholders(expr, params)
    if list(expr.find_all(exp.Join)):
        return FallbackReactive(tables, sql, expr)
    try:
        return build_reactive(expr, tables)
    except NotImplementedError:
        return FallbackReactive(tables, sql, expr)
