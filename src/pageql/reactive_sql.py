import sqlglot
from sqlglot import expressions as exp
from .reactive import (
    Tables,
    Select,
    Where,
    Union,
    UnionAll,
    Aggregate,
    DerivedSignal,
    DerivedSignal2,
    OneValue,
    Signal,
    ReadOnly,
    Join,
    Order,
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

    placeholders = list(expr.find_all(exp.Placeholder))
    missing = [ph.this for ph in placeholders if ph.this not in params]
    if missing:
        names = ", ".join(missing)
        raise ValueError(
            f"Missing parameter(s) {names} for SQL expression `{expr.sql()}`."
        )

    for ph in placeholders:
        name = ph.this
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


def _apply_order_limit_offset(
    node, expr, tables: Tables, alias_map: set[str] | None = None, alias_repl: dict[str, str] | None = None
):
    """Attach an :class:`Order` component if needed."""

    order = expr.args.get("order")
    limit_expr = expr.args.get("limit")
    offset_expr = expr.args.get("offset")

    if not any((order, limit_expr, offset_expr)):
        return node

    order_sql = ""
    if order is not None:
        order_sql = order.sql(dialect=tables.dialect)[len("ORDER BY ") :]
        if alias_repl:
            for k, v in alias_repl.items():
                order_sql = order_sql.replace(k, v)
        elif alias_map:
            for a in alias_map:
                order_sql = order_sql.replace(f"{a}.", "")

    limit_val = None
    if limit_expr is not None and limit_expr.expression is not None:
        lit = limit_expr.expression
        try:
            limit_val = int(getattr(lit, "this", getattr(lit, "name", lit)))
        except Exception:
            limit_val = int(lit.sql(dialect=tables.dialect))

    offset_val = 0
    if offset_expr is not None and offset_expr.this is not None:
        lit = offset_expr.this
        try:
            offset_val = int(getattr(lit, "this", getattr(lit, "name", lit)))
        except Exception:
            offset_val = int(lit.sql(dialect=tables.dialect))

    return Order(node, order_sql, limit=limit_val, offset=offset_val)


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

        joins = expr.args.get("joins") or []
        alias_map = None
        if not joins and isinstance(from_expr.this, exp.Table) and from_expr.this.alias:
            alias_map = {from_expr.this.alias_or_name}
        if joins:
            if len(joins) > 1:
                raise NotImplementedError("multiple joins not supported")
            j = joins[0]
            if j.args.get("method") is not None or j.args.get("kind") in {"CROSS"} or j.args.get("using") is not None or j.args.get("on") is None:
                raise NotImplementedError("unsupported join")
            right = build_from(j.this, tables)
            left_alias = from_expr.this.alias_or_name
            right_alias = j.this.alias_or_name
            on_sql = j.args["on"].sql(dialect=tables.dialect)
            on_sql = on_sql.replace(f"{left_alias}.", "__LEFT__.")
            on_sql = on_sql.replace(f"{right_alias}.", "__RIGHT__.")
            on_sql = on_sql.replace("__LEFT__.", "a.")
            on_sql = on_sql.replace("__RIGHT__.", "b.")
            side = j.args.get("side")
            left_outer = side in ("LEFT", "FULL")
            right_outer = side in ("RIGHT", "FULL")
            parent = Join(parent, right, on_sql, left_outer=left_outer, right_outer=right_outer)
            alias_map = {left_alias, right_alias}

        if expr.args.get("where"):
            where_sql = expr.args["where"].this.sql(dialect=tables.dialect)
            if alias_map:
                for a in alias_map:
                    where_sql = where_sql.replace(f"{a}.", "")
            parent = Where(parent, where_sql)

        group_sql = None
        group = expr.args.get("group")
        if group is not None:
            gcols = []
            for g in group.expressions:
                if alias_map and isinstance(g, exp.Column) and g.table in alias_map:
                    gcols.append(g.name)
                else:
                    gcols.append(g.sql(dialect=tables.dialect))
            group_sql = ", ".join(gcols)

        select_list = expr.args.get("expressions") or [exp.Star()]
        if len(select_list) == 1:
            col = select_list[0]
            if isinstance(col, exp.Star):
                return _apply_order_limit_offset(parent, expr, tables, alias_map)
            if isinstance(col, exp.Count) and not col.args.get("distinct"):
                expr_sql = col.sql(dialect=tables.dialect)
                node = Aggregate(parent, (expr_sql,))
                return _apply_order_limit_offset(node, expr, tables, alias_map)
            if isinstance(col, exp.Sum):
                expr_sql = col.sql(dialect=tables.dialect)
                node = Aggregate(parent, (expr_sql,))
                return _apply_order_limit_offset(node, expr, tables, alias_map)
            if isinstance(col, exp.Avg):
                expr_sql = col.sql(dialect=tables.dialect)
                node = Aggregate(parent, (expr_sql,))
                return _apply_order_limit_offset(node, expr, tables, alias_map)

        if group_sql is not None:
            agg_exprs = []
            ok = True
            for c in select_list:
                e = c.this if isinstance(c, exp.Alias) else c
                if isinstance(e, exp.Column):
                    continue
                if isinstance(e, exp.Count) and not e.args.get("distinct"):
                    expr_sql = c.sql(dialect=tables.dialect)
                elif isinstance(e, (exp.Sum, exp.Avg, exp.Min, exp.Max)):
                    expr_sql = c.sql(dialect=tables.dialect)
                else:
                    ok = False
                    break
                if alias_map:
                    for a in alias_map:
                        expr_sql = expr_sql.replace(f"{a}.", "")
                agg_exprs.append(expr_sql)
            if ok and agg_exprs:
                node = Aggregate(parent, tuple(agg_exprs), group_by=group_sql)
                return _apply_order_limit_offset(node, expr, tables, alias_map)

        cols = []
        alias_repl = {}
        for c in select_list:
            if alias_map and isinstance(c, exp.Column) and c.table in alias_map:
                cols.append(c.name)
                alias_repl[f"{c.table}.{c.name}"] = c.name
            elif alias_map and isinstance(c, exp.Alias) and isinstance(c.this, exp.Column) and c.this.table in alias_map:
                cols.append(f"{c.this.name} AS {c.alias_or_name}")
                alias_repl[f"{c.this.table}.{c.this.name}"] = c.alias_or_name
            else:
                col_sql = c.sql(dialect=tables.dialect)
                if alias_map:
                    for a in alias_map:
                        col_sql = col_sql.replace(f"{a}.", "")
                cols.append(col_sql)
        select_sql = ", ".join(cols)
        node = Select(parent, select_sql)
        return _apply_order_limit_offset(node, expr, tables, alias_map, alias_repl or None)
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

    try:
        comp = build_reactive(expr, tables)
    except NotImplementedError:
        comp = FallbackReactive(tables, sql, expr)

    if one_value:
        comp = OneValue(comp)

    if cache:
        _CACHE[cache_key] = comp

    return comp
