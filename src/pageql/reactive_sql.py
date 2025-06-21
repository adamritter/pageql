import sqlglot
from sqlglot import expressions as exp
from .reactive import (
    Tables,
    Select,
    Where,
    Union,
    UnionAll,
    CountAll,
    DerivedSignal,
    DerivedSignal2,
    OneValue,
    Signal,
    ReadOnly,
    execute,
)


def _replace_placeholders(
    expr: exp.Expression,
    params: dict[str, object] | None,
    dialect: str = "sqlite",
) -> None:
    """Replace ``Placeholder`` nodes in *expr* using values from *params*.

    ``dialect`` controls how binary literals are emitted.
    """

    if not params:
        return

    for ph in list(expr.find_all(exp.Placeholder)):
        name = ph.this
        if name not in params:
            continue
        val = params[name]
        if isinstance(val, Signal):
            val = val.value
        if val is None:
            lit = exp.Null()
        elif isinstance(val, (int, float)):
            lit = exp.Literal.number(val)
        elif isinstance(val, (bytes, bytearray)):
            if dialect == "mysql":
                lit = exp.Literal(this="0x" + val.hex(), is_string=False)
            else:
                lit = exp.Literal(this=f"X'{val.hex()}'", is_string=False)
        else:
            lit = exp.Literal.string(str(val))
        ph.replace(lit)


class FallbackReactive(Signal):
    """Generic reactive component for unsupported queries."""

    def __init__(self, tables: Tables, sql: str, expr: exp.Expression | None = None):
        super().__init__(None)
        self.tables = tables
        self.conn = tables.conn
        self.sql = sql

        if expr is None:
            expr = sqlglot.parse_one(sql, read=tables.dialect)

        # Determine table dependencies
        cte_names = {c.alias_or_name for c in expr.find_all(exp.CTE)}
        self.deps = []
        for tbl in expr.find_all(exp.Table):
            if tbl.name in cte_names:
                continue
            dep = tables._get(tbl.name)
            self.deps.append(dep)
            dep.listeners.append(self._on_parent_event)
        self.update = self._on_parent_event

        cur = execute(self.conn, sql, [])
        self.columns = [d[0] for d in cur.description]
        self.rows = list(cur.fetchall())
        self._counts = {}
        for r in self.rows:
            self._counts[r] = self._counts.get(r, 0) + 1

    def _emit(self, event):
        for l in list(self.listeners):
            l(event)

    def _on_parent_event(self, _):
        cur = execute(self.conn, self.sql, [])
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
        super().remove_listener(listener)
        if self.listeners is None:
            for dep in self.deps:
                dep.remove_listener(self._on_parent_event)



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
            return FallbackReactive(tables, expr.sql(dialect=tables.dialect))
        parent = build_from(from_expr.this, tables)
        if expr.args.get("where"):
            parent = Where(parent, expr.args["where"].this.sql(dialect=tables.dialect))
        select_list = expr.args.get("expressions") or [exp.Star()]
        if len(select_list) == 1:
            col = select_list[0]
            if isinstance(col, exp.Star):
                return parent
            if isinstance(col, exp.Count):
                if isinstance(col.this, exp.Star):
                    return CountAll(parent)
                if not col.args.get("distinct"):
                    expr_sql = col.this.sql(dialect=tables.dialect)
                    return CountAll(parent, expr_sql)
        select_sql = ", ".join(col.sql(dialect=tables.dialect) for col in select_list)
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


_CACHE: dict[tuple[int, str], Signal] = {}


def parse_reactive(
    expr: exp.Expression,
    tables: Tables,
    params: dict[str, object] | None = None,
    *,
    cache: bool = True,
    one_value: bool = False,
):
    """Parse a SQL ``Expression`` into reactive components.

    Placeholders in *expr* are replaced using *params* before building the
    reactive expression tree.
    """
    expr = expr.copy()
    _replace_placeholders(expr, params, tables.dialect)
    sql = expr.sql(dialect=tables.dialect)

    if "randomblob" in sql.lower():
        cache = False

    cache_key = None
    if cache:
        cache_key = (id(tables), sql, one_value)
        comp = _CACHE.get(cache_key)
        if comp is not None and comp.listeners:
            return comp

    # If the expression references no tables (ignoring CTEs) the result is
    # constant, so return a simple ReadOnly wrapper instead of a reactive
    # component.
    cte_names = {c.alias_or_name for c in expr.find_all(exp.CTE)}
    table_refs = [t for t in expr.find_all(exp.Table) if t.name not in cte_names]
    if not table_refs:
        cur = execute(tables.conn, sql, [])
        if one_value:
            row = cur.fetchone()
            comp = ReadOnly(row[0] if row else None)
        else:
            rows = cur.fetchall()
            comp = ReadOnly(rows)
        comp.sql = sql
        comp.columns = [d[0] for d in cur.description]
        return comp

    if list(expr.find_all(exp.Join)):
        comp = FallbackReactive(tables, sql, expr)
    else:
        try:
            comp = build_reactive(expr, tables)
        except NotImplementedError:
            comp = FallbackReactive(tables, sql, expr)

    if one_value:
        comp = OneValue(comp)

    if cache:
        _CACHE[cache_key] = comp

    return comp
