import re
from collections import Counter
import sqlglot

def execute(conn, sql, params):
    try:
        cursor = conn.execute(sql, params)
    except Exception as e:
        raise Exception(f"Execute failed for query: {sql} with params: {params} with error: {e}")
    return cursor



class Signal:
    """Basic observable value container."""

    def __init__(self, value=None):
        self.listeners = []
        self.value = value

    def set_value(self, value):
        if self.value != value:
            self.value = value
            for l in list(self.listeners):
                l(value)

    def remove_listener(self, listener):
        """Remove *listener* from ``listeners`` and cleanup dependencies."""
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            self.listeners = None


class ReadOnly(Signal):
    """Simple wrapper for read-only parameters."""

    def __init__(self, value):
        super().__init__(value)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


def get_dependencies(expr):
    """Return parameter names referenced in *expr*.

    Parameters inside quoted strings or comments are ignored. Names are
    returned in the order of first appearance without duplicates.
    """
    # Remove single and double quoted strings to avoid false matches
    cleaned = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", "", expr)
    # Strip SQL comments
    cleaned = re.sub(r"--.*?$|/\*.*?\*/", "", cleaned, flags=re.S | re.M)
    deps = []
    for name in re.findall(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", cleaned):
        if name not in deps:
            deps.append(name)
    return deps


class DerivedSignal(Signal):
    def __init__(self, f, deps):
        super().__init__(f())
        self.f = f
        self.deps = deps
        for dep in deps:
            dep.listeners.append(self.update)

    def update(self, _=None):
        self.set_value(self.f())

    def remove_listener(self, listener):
        super().remove_listener(listener)
        if self.listeners is None:
            for dep in self.deps:
                dep.remove_listener(self.update)

    def replace(self, f, deps):
        """Replace the compute function and dependencies.

        Removes the current :py:meth:`update` listener from all previous
        dependencies, attaches it to ``deps`` and recomputes the value.  If the
        recomputed value differs from the previous one a change event is
        emitted.
        """

        # detach from old dependencies
        for dep in self.deps:
            if self.update in getattr(dep, "listeners", []):
                dep.listeners.remove(self.update)

        # store new function and deps
        self.f = f
        self.deps = deps

        # attach to new deps
        for dep in deps:
            dep.listeners.append(self.update)

        # recompute and notify if changed
        self.set_value(self.f())


class DerivedSignal2(Signal):
    """Signal derived from another signal returned by a callback."""

    def __init__(self, f, deps):
        """Create a DerivedSignal2.

        Parameters
        ----------
        f : callable
            Function returning the signal to track. Warning: this signal will be listened and then unlistened, so it
            may not be reusable and need to be recreated.
        deps : list[Signal]
            Extra dependency signals. When any of them changes ``f`` is
            evaluated again to obtain the new main signal.
        """

        self.f = f
        self.deps = deps
        self.main = f()
        if not isinstance(self.main, Signal):
            raise ValueError("DerivedSignal2 callback must return a Signal")

        super().__init__(self.main.value)

        self._on_main = lambda _=None: self.set_value(self.main.value)
        self.main.listeners.append(self._on_main)

        self.update = self._on_dep
        for dep in deps:
            dep.listeners.append(self._on_dep)

    def _on_dep(self, _=None):
        self.main.remove_listener(self._on_main)
        self.main = self.f()
        if not isinstance(self.main, Signal):
            raise ValueError("DerivedSignal2 callback must return a Signal")
        self.main.listeners.append(self._on_main)
        self.set_value(self.main.value)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            for dep in self.deps:
                dep.remove_listener(self._on_dep)
            self.main.remove_listener(self._on_main)
            self.listeners = None


def derive_signal2(f, deps):
    """Return a :class:`DerivedSignal2` tracking *deps* if any are writable."""

    if not deps or all(isinstance(d, ReadOnly) for d in deps):
        return f()

    deps = [d for d in deps if isinstance(d, Signal) and not isinstance(d, ReadOnly)]
    return DerivedSignal2(f, deps)


def _normalize_params(params):
    """Return a copy of *params* with signal-like objects replaced by their values."""

    normalized = {}
    for k, v in params.items():
        if isinstance(v, Signal):
            normalized[k] = v.value
        else:
            normalized[k] = v
    return normalized

_DOT_PARAM_RE = re.compile(r":([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)")

def _convert_dot_sql(sql: str) -> str:
    """Return *sql* with ``:a.b`` placeholders rewritten as ``:a__b``."""

    return _DOT_PARAM_RE.sub(lambda m: ":" + m.group(1).replace(".", "__"), sql)

class ReactiveTable(Signal):
    def __init__(self, conn, table_name):
        super().__init__()
        self.conn = conn
        self.table_name = table_name
        cur = execute(self.conn, f"PRAGMA table_info({self.table_name})", [])
        self.columns = [col[1] for col in cur]
        self.sql = f"SELECT * FROM {self.table_name}"

    def remove_listener(self, listener):
        """Remove *listener* but don't set listeners to None as ReactiveTable can be reused."""
        if listener in self.listeners:
            self.listeners.remove(listener)

    def insert(self, sql, params):
        params = _normalize_params(params)
        query = _convert_dot_sql(sql + " RETURNING *")
        try:
            cursor = execute(self.conn, query, params)
            row = cursor.fetchone()
        except Exception as e:
            from .pageql import RenderResultException
            if isinstance(e, RenderResultException):
                raise
            raise Exception(
                f"Insert into table {self.table_name} failed for query: {query} with params: {params} with error: {e}"
            )
        if row is None:
            # insert .. or ignore may not return a row when it affects nothing
            # In this case the statement had no effect so we don't emit events
            return
        for listener in self.listeners:
            listener([1, row])
            
    def delete(self, sql, params):
        """
        Delete rows **one by one**, notifying listeners after each deletion.
        """
        params = _normalize_params(params)
        query = _convert_dot_sql(sql + " RETURNING * LIMIT 1")
        try:
            while True:
                cursor = execute(self.conn, query, params)
                row = cursor.fetchone()
                if row is None:
                    break
                for listener in self.listeners:
                    listener([2, row])
        except Exception as e:
            from .pageql import RenderResultException
            if isinstance(e, RenderResultException):
                raise
            raise Exception(
                f"Delete from table {self.table_name} failed for query: {query} with params: {params} with error: {e}"
            )

    def update(self, sql, params):
        """
        Update rows **one by one**, notifying listeners after each update.
        """
        params = _normalize_params(params)
        m = re.search(r'update\s+([^\s]+)\s+set\s+(.*?)(?:\s+where\s+(.*?))?;?\s*$', sql, re.I | re.S)
        if not m:
            raise ValueError(f"Couldn’t parse UPDATE statement {sql}")
        table, set_sql, where = m.groups()
        select_sql = f"SELECT * FROM {table}"
        if where:
            select_sql += f" WHERE {where.rstrip()}"
        select_sql += ";"
        cursor = execute(self.conn, _convert_dot_sql(select_sql), params)
        rows = cursor.fetchall()
        update_sql = f"UPDATE {table} SET {set_sql} WHERE {' AND '.join([f'{k} IS :_col{index}' for index, k in enumerate(self.columns)])} RETURNING * LIMIT 1"
        params = params.copy()
        for row in rows:
            for index, value in enumerate(row):
                params[f"_col{index}"] = value
            cursor = execute(self.conn, _convert_dot_sql(update_sql), params)
            new_row = cursor.fetchone()
            if new_row is None:
                raise Exception(f"Update on table {self.table_name} failed for query: {update_sql} with params: {params}")
            if new_row == row:
                continue
            for listener in self.listeners:
                listener([3, row, new_row])
            
class Where(Signal):
    def __init__(self, parent, where_sql):
        super().__init__()
        self.parent = parent
        self.where_sql = where_sql
        self.columns = self.parent.columns
        self.conn = self.parent.conn
        self.filter_sql = f"SELECT {', '.join([f'? as {col}' for col in self.columns])} WHERE {self.where_sql}"
        self.sql = f"SELECT * FROM ({self.parent.sql}) WHERE {self.where_sql}"
        self.parent.listeners.append(self.onevent)
        self.deps = [self.parent]
        self.update = self.onevent

    def contains_row(self, row):
        cursor = execute(self.conn, self.filter_sql, row)
        return cursor.fetchone() is not None
    
    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            self.parent.remove_listener(self.onevent)
            self.listeners = None
    
    def onevent(self, event):
        if event[0] < 3:
            row = event[1]
            if self.contains_row(row):
                for listener in self.listeners:
                    listener([event[0], row])
        else:
            contains_old_row = self.contains_row(event[1])
            contains_new_row = self.contains_row(event[2])
            if event[1] == event[2]:
                return
            if contains_old_row and not contains_new_row:
                for listener in self.listeners:
                    listener([2, event[1]])
            elif not contains_old_row and contains_new_row:
                for listener in self.listeners:
                    listener([1, event[2]])
            elif contains_old_row and contains_new_row:
                for listener in self.listeners:
                    listener([3, event[1], event[2]])


class Aggregate(Signal):
    def __init__(self, parent, exprs=("COUNT(*)",), group_by=None):
        super().__init__(None)
        self.parent = parent
        if isinstance(exprs, str):
            exprs = (exprs,)
        self.exprs = tuple(exprs)
        self.group_by = group_by
        self.conn = self.parent.conn

        self._funcs = []
        self._inners = []
        self._expr_sqls = []
        self._avg_counts = []
        self._avg_sums = []
        self._recompute = []
        columns = []
        for expr in self.exprs:
            m = re.fullmatch(
                r"\s*(count|sum|avg|min|max)\s*\(\s*(\*|[^)]*)\s*\)\s*",
                expr,
                re.I,
            )
            if not m or (
                m.group(1).lower() in {"sum", "avg", "min", "max"}
                and m.group(2).strip() == "*"
            ):
                self._funcs.append(None)
                self._inners.append(None)
                self._expr_sqls.append(None)
                self._avg_counts.append(None)
                self._avg_sums.append(None)
                self._recompute.append(False)
                columns.append(expr)
                continue

            func = m.group(1).lower()
            inner = m.group(2).strip()
            inner_val = None if inner == "*" else inner
            self._funcs.append(func)
            self._inners.append(inner_val)
            columns.append(f"{func.upper()}({inner})")
            if func == "count" and inner_val is None:
                self._expr_sqls.append(None)
            else:
                placeholders = ", ".join(f"? AS {c}" for c in self.parent.columns)
                self._expr_sqls.append(
                    f"SELECT {inner} FROM (SELECT {placeholders})"
                )
            if func == "avg":
                count_sql = f"SELECT COUNT({inner}) FROM ({self.parent.sql})"
                sum_sql = f"SELECT SUM({inner}) FROM ({self.parent.sql})"
                c = execute(self.conn, count_sql, []).fetchone()[0]
                s = execute(self.conn, sum_sql, []).fetchone()[0]
                self._avg_counts.append(0 if c is None else c)
                self._avg_sums.append(0 if s is None else s)
            else:
                self._avg_counts.append(None)
                self._avg_sums.append(None)
            self._recompute.append(False)

        if self.group_by is None:
            self.sql = f"SELECT {', '.join(self.exprs)} FROM ({self.parent.sql})"

            row = execute(self.conn, self.sql, []).fetchone()
            self.value = []
            for v, func in zip(row, self._funcs):
                if v is None:
                    self.value.append(0 if func in {"count", "sum", "avg"} else None)
                else:
                    self.value.append(v)
            self.parent.listeners.append(self.onevent)
            self.columns = columns[0] if len(columns) == 1 else columns
            self.deps = [self.parent]
            self.update = self.onevent
        else:
            expr_sql = ", ".join(self.exprs)
            self.sql = (
                f"SELECT {self.group_by}, {expr_sql} FROM ({self.parent.sql}) "
                f"GROUP BY {self.group_by}"
            )
            cur = execute(self.conn, self.sql, [])
            self.columns = [d[0] for d in cur.description]
            self._group_cols = len(self.columns) - len(self.exprs)
            self.rows = list(cur.fetchall())
            self._map = {row[: self._group_cols]: row for row in self.rows}
            self.parent.listeners.append(self.onevent)
            self.deps = [self.parent]
            self.update = self.onevent

    def _expr_not_null(self, idx, row):
        if self._inners[idx] is None:
            return True
        cur = execute(self.conn, self._expr_sqls[idx], row)
        return cur.fetchone()[0] is not None

    def _expr_value(self, idx, row):
        cur = execute(self.conn, self._expr_sqls[idx], row)
        val = cur.fetchone()[0]
        return 0 if val is None else val

    def onevent(self, event):
        if self.group_by is None:
            oldvalue = list(self.value)
            if event[0] == 1:
                for i, func in enumerate(self._funcs):
                    if func is None:
                        continue
                    if func == "count":
                        if self._expr_not_null(i, event[1]):
                            self.value[i] += 1
                    elif func == "sum":
                        self.value[i] += self._expr_value(i, event[1])
                    elif func == "avg":
                        if self._expr_not_null(i, event[1]):
                            val = self._expr_value(i, event[1])
                            self._avg_counts[i] += 1
                            self._avg_sums[i] += val
                            self.value[i] = self._avg_sums[i] / self._avg_counts[i]
                    elif func == "min":
                        if self._expr_not_null(i, event[1]):
                            val = self._expr_value(i, event[1])
                            if self.value[i] is None or val < self.value[i]:
                                self.value[i] = val
                    else:  # max
                        if self._expr_not_null(i, event[1]):
                            val = self._expr_value(i, event[1])
                            if self.value[i] is None or val > self.value[i]:
                                self.value[i] = val
            elif event[0] == 2:
                for i, func in enumerate(self._funcs):
                    if func is None:
                        continue
                    if func == "count":
                        if self._expr_not_null(i, event[1]):
                            self.value[i] -= 1
                    elif func == "sum":
                        self.value[i] -= self._expr_value(i, event[1])
                    elif func == "avg":
                        if self._expr_not_null(i, event[1]):
                            val = self._expr_value(i, event[1])
                            self._avg_counts[i] -= 1
                            self._avg_sums[i] -= val
                            if self._avg_counts[i]:
                                self.value[i] = self._avg_sums[i] / self._avg_counts[i]
                            else:
                                self.value[i] = 0
                    elif func == "min":
                        if self._expr_not_null(i, event[1]):
                            val = self._expr_value(i, event[1])
                            if self.value[i] is not None and val == self.value[i]:
                                self._recompute[i] = True
                    else:  # max
                        if self._expr_not_null(i, event[1]):
                            val = self._expr_value(i, event[1])
                            if self.value[i] is not None and val == self.value[i]:
                                self._recompute[i] = True
            elif event[0] == 3 and self.exprs is not None:
                for i, func in enumerate(self._funcs):
                    if func is None:
                        continue
                    if func == "count":
                        before = self._expr_not_null(i, event[1])
                        after = self._expr_not_null(i, event[2])
                        self.value[i] += int(after) - int(before)
                    elif func == "sum":
                        before = self._expr_value(i, event[1])
                        after = self._expr_value(i, event[2])
                        self.value[i] += after - before
                    elif func == "avg":
                        before_n = self._expr_not_null(i, event[1])
                        after_n = self._expr_not_null(i, event[2])
                        before_v = self._expr_value(i, event[1]) if before_n else 0
                        after_v = self._expr_value(i, event[2]) if after_n else 0
                        if before_n:
                            self._avg_counts[i] -= 1
                            self._avg_sums[i] -= before_v
                        if after_n:
                            self._avg_counts[i] += 1
                            self._avg_sums[i] += after_v
                        if self._avg_counts[i]:
                            self.value[i] = self._avg_sums[i] / self._avg_counts[i]
                        else:
                            self.value[i] = 0
                    elif func == "min":
                        before_n = self._expr_not_null(i, event[1])
                        after_n = self._expr_not_null(i, event[2])
                        before_v = self._expr_value(i, event[1]) if before_n else None
                        after_v = self._expr_value(i, event[2]) if after_n else None
                        if after_n and (self.value[i] is None or after_v < self.value[i]):
                            self.value[i] = after_v
                        if before_n and before_v == self.value[i] and (not after_n or after_v > before_v):
                            self._recompute[i] = True
                    else:  # max
                        before_n = self._expr_not_null(i, event[1])
                        after_n = self._expr_not_null(i, event[2])
                        before_v = self._expr_value(i, event[1]) if before_n else None
                        after_v = self._expr_value(i, event[2]) if after_n else None
                        if after_n and (self.value[i] is None or after_v > self.value[i]):
                            self.value[i] = after_v
                        if before_n and before_v == self.value[i] and (not after_n or after_v < before_v):
                            self._recompute[i] = True
            if any(self._recompute):
                row = execute(self.conn, self.sql, []).fetchone()
                for idx, flag in enumerate(self._recompute):
                    if flag:
                        val = row[idx]
                        if val is None and self._funcs[idx] in {"count", "sum", "avg"}:
                            self.value[idx] = 0
                        else:
                            self.value[idx] = val
                        self._recompute[idx] = False

            if oldvalue != self.value:
                for listener in self.listeners:
                    listener([3, oldvalue, list(self.value)])
        else:
            cur = execute(self.conn, self.sql, [])
            rows = list(cur.fetchall())
            new_map = {row[: self._group_cols]: row for row in rows}

            for key, new_row in new_map.items():
                if key not in self._map:
                    for listener in self.listeners:
                        listener([1, new_row])
                else:
                    old_row = self._map[key]
                    if old_row != new_row:
                        for listener in self.listeners:
                            listener([3, old_row, new_row])

            for key, old_row in list(self._map.items()):
                if key not in new_map:
                    for listener in self.listeners:
                        listener([2, old_row])

            self.rows = rows
            self._map = new_map
    
    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            self.parent.remove_listener(self.onevent)
            self.listeners = None


class OneValue(Signal):
    """Wrap a reactive relation expected to yield a single-column row."""

    def __init__(self, parent):
        self.parent = parent
        self.conn = self.parent.conn
        self.sql = self.parent.sql
        cols = self.parent.columns
        if isinstance(cols, str):
            cols = [cols]
        if len(cols) != 1:
            raise ValueError("OneValue parent must have exactly one column")
        self.columns = cols[0]
        row = execute(self.conn, self.sql, []).fetchone()
        super().__init__(row[0] if row else None)
        self.parent.listeners.append(self.onevent)

    def __str__(self):
        return str(self.value)

    def reset(self, parent):
        """Switch to *parent* and recompute the value."""

        # detach from old parent
        if self.onevent in getattr(self.parent, "listeners", []):
            self.parent.listeners.remove(self.onevent)

        self.parent = parent
        self.conn = parent.conn
        self.sql = parent.sql

        cols = parent.columns
        if isinstance(cols, str):
            cols = [cols]
        if len(cols) != 1:
            raise ValueError("OneValue parent must have exactly one column")

        self.columns = cols[0]
        parent.listeners.append(self.onevent)
        self.deps = [parent]

        row = execute(self.conn, self.sql, []).fetchone()
        value = row[0] if row else None

        self.set_value(value)

    def remove_listener(self, listener):
        """Remove *listener* and detach from parent when unused."""
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            if hasattr(self.parent, "remove_listener"):
                self.parent.remove_listener(self.onevent)
            elif self.onevent in getattr(self.parent, "listeners", []):
                self.parent.listeners.remove(self.onevent)

            keep = getattr(self.parent, "_keepalive", None)
            if keep is None:
                keep = self.parent._keepalive = (lambda *_: None)
            if self.parent.listeners is None:
                self.parent.listeners = [keep]
            elif keep not in self.parent.listeners:
                self.parent.listeners.append(keep)

            self.listeners = None

    def onevent(self, event):
        if event[0] == 1:
            value = event[1][0]
        elif event[0] == 2:
            value = None
        else:
            value = event[2][0]
        self.set_value(value)


class UnionAll(Signal):
    def __init__(self, parent1, parent2):
        super().__init__(None)
        self.parent1 = parent1
        self.parent2 = parent2
        self.conn = self.parent1.conn
        self.sql = f"SELECT * FROM ({self.parent1.sql}) UNION ALL SELECT * FROM ({self.parent2.sql})"
        self.parent1.listeners.append(self.onevent)
        self.parent2.listeners.append(self.onevent)
        self.columns = self.parent1.columns
        if self.parent1.columns != self.parent2.columns:
            raise ValueError(f"UnionAll: parent1 and parent2 must have the same columns {self.parent1.columns} != {self.parent2.columns}")
        self.deps = [self.parent1, self.parent2]
        self.update = self.onevent

    def onevent(self, event):
        for listener in self.listeners:
            listener(event)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            self.parent1.remove_listener(self.onevent)
            self.parent2.remove_listener(self.onevent)
            self.listeners = None



class Union(Signal):
    def __init__(self, parent1, parent2):
        super().__init__(None)
        self.parent1 = parent1
        self.parent2 = parent2
        self.conn = self.parent1.conn
        self.sql = f"SELECT * FROM ({self.parent1.sql}) UNION SELECT * FROM ({self.parent2.sql})"
        self._cb1 = lambda e: self.onevent(e, 1)
        self._cb2 = lambda e: self.onevent(e, 2)
        self.parent1.listeners.append(self._cb1)
        self.parent2.listeners.append(self._cb2)
        self.columns = self.parent1.columns
        if self.parent1.columns != self.parent2.columns:
            raise ValueError(
                f"Union: parent1 and parent2 must have the same columns {self.parent1.columns} != {self.parent2.columns}"
            )

        where = " AND ".join([f"{c} IS ?" for c in self.columns])
        self._contains1 = f"SELECT 1 FROM ({self.parent1.sql}) WHERE {where} LIMIT 1"
        self._contains2 = f"SELECT 1 FROM ({self.parent2.sql}) WHERE {where} LIMIT 1"
        self.deps = [self.parent1, self.parent2]
        self.update = self.onevent

    def _emit(self, event):
        for listener in self.listeners:
            listener(event)

    def _in_parent1(self, row):
        return execute(self.conn, self._contains1, row).fetchone() is not None

    def _in_parent2(self, row):
        return execute(self.conn, self._contains2, row).fetchone() is not None

    def _insert(self, row, which):
        if which == 1:
            if not self._in_parent2(row):
                self._emit([1, row])
        else:
            if not self._in_parent1(row):
                self._emit([1, row])

    def _delete(self, row, which):
        if which == 1:
            if not self._in_parent2(row):
                self._emit([2, row])
        else:
            if not self._in_parent1(row):
                self._emit([2, row])

    def _update(self, oldrow, newrow, which):
        if oldrow == newrow:
            return
        if which == 1:
            old_other = self._in_parent2(oldrow)
            new_other = self._in_parent2(newrow)
        else:
            old_other = self._in_parent1(oldrow)
            new_other = self._in_parent1(newrow)

        if not old_other and not new_other:
            self._emit([3, oldrow, newrow])
        elif not old_other and new_other:
            self._emit([2, oldrow])
        elif old_other and not new_other:
            self._emit([1, newrow])

    def onevent(self, event, which):
        if event[0] == 1:
            self._insert(event[1], which)
        elif event[0] == 2:
            self._delete(event[1], which)
        else:
            self._update(event[1], event[2], which)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            for parent, cb in ((self.parent1, self._cb1), (self.parent2, self._cb2)):
                parent.remove_listener(cb)
            self.listeners = None



class Intersect(Signal):
    def __init__(self, parent1, parent2):
        super().__init__(None)
        self.parent1 = parent1
        self.parent2 = parent2
        self.conn = self.parent1.conn
        self.sql = (
            f"SELECT * FROM ({self.parent1.sql}) INTERSECT SELECT * FROM ({self.parent2.sql})"
        )
        self._cb1 = lambda e: self.onevent(e, 1)
        self._cb2 = lambda e: self.onevent(e, 2)
        self.parent1.listeners.append(self._cb1)
        self.parent2.listeners.append(self._cb2)
        self.deps = [self.parent1, self.parent2]
        self.columns = self.parent1.columns
        if self.parent1.columns != self.parent2.columns:
            raise ValueError(
                f"Intersect: parent1 and parent2 must have the same columns {self.parent1.columns} != {self.parent2.columns}"
            )

        # Set of rows currently present in the intersection
        self._rows = set(execute(self.conn, self.sql, []).fetchall())

        qcols = " AND ".join([f"{c} IS ?" for c in self.columns])
        self._exists_sql1 = f"SELECT 1 FROM ({self.parent1.sql}) WHERE {qcols} LIMIT 1"
        self._exists_sql2 = f"SELECT 1 FROM ({self.parent2.sql}) WHERE {qcols} LIMIT 1"

    def _emit(self, event):
        for listener in self.listeners:
            listener(event)

    def _exists1(self, row):
        return execute(self.conn, self._exists_sql1, row).fetchone() is not None

    def _exists2(self, row):
        return execute(self.conn, self._exists_sql2, row).fetchone() is not None

    def _insert(self, row, which):
        if which == 1:
            other_exists = self._exists2(row)
        else:
            other_exists = self._exists1(row)
        if other_exists and row not in self._rows:
            self._rows.add(row)
            self._emit([1, row])

    def _delete(self, row, which):
        if which == 1:
            exists_self = self._exists1(row)
            exists_other = self._exists2(row)
        else:
            exists_self = self._exists2(row)
            exists_other = self._exists1(row)
        if row in self._rows and (not exists_self or not exists_other):
            self._rows.remove(row)
            self._emit([2, row])

    def _update(self, oldrow, newrow, which):
        if oldrow == newrow:
            return
        self._delete(oldrow, which)
        self._insert(newrow, which)

    def onevent(self, event, which):
        if event[0] == 1:
            self._insert(event[1], which)
        elif event[0] == 2:
            self._delete(event[1], which)
        else:
            self._update(event[1], event[2], which)

    def remove_listener(self, listener):
        """Remove *listener* and detach from parents when unused."""
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            for parent, cb in ((self.parent1, self._cb1), (self.parent2, self._cb2)):
                parent.remove_listener(cb)
            self.listeners = None


class Order(Signal):
    def __init__(self, parent, order_sql):
        super().__init__(None)
        self.parent = parent
        self.order_sql = order_sql
        self.conn = self.parent.conn
        self.sql = f"SELECT * FROM ({self.parent.sql}) ORDER BY {self.order_sql}"
        self.columns = self.parent.columns
        self.parent.listeners.append(self.onevent)
        self.deps = [self.parent]
        self.update = self.onevent

        placeholders = ", ".join([f'? as {c}' for c in self.columns])
        self._compare_sql = (
            f"SELECT idx FROM (SELECT 0 as idx, {placeholders} UNION ALL "
            f"SELECT 1 as idx, {placeholders}) ORDER BY {self.order_sql} LIMIT 1"
        )

        cur = execute(self.conn, self.sql, [])
        self.value = list(cur.fetchall())

    def _fetch_rows(self):
        cur = execute(self.conn, self.sql, [])
        return list(cur.fetchall())

    def _compare(self, row1, row2):
        idx = execute(self.conn, self._compare_sql, list(row1) + list(row2)).fetchone()[0]
        return idx == 0

    def _bisect(self, row):
        lo, hi = 0, len(self.value)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._compare(row, self.value[mid]):
                hi = mid
            else:
                lo = mid + 1
        return lo

    def onevent(self, event):
        if event[0] == 1:
            row = event[1]
            idx = self._bisect(row)
            self.value.insert(idx, row)
            for l in self.listeners:
                l([1, idx, row])
        elif event[0] == 2:
            row = event[1]
            try:
                idx = self.value.index(row)
            except ValueError:
                idx = -1
            if idx != -1:
                self.value.pop(idx)
                for l in self.listeners:
                    l([2, idx])
        else:
            oldrow, newrow = event[1], event[2]
            try:
                old_idx = self.value.index(oldrow)
            except ValueError:
                old_idx = -1
            if old_idx != -1:
                self.value.pop(old_idx)
            new_idx = self._bisect(newrow)
            self.value.insert(new_idx, newrow)
            if old_idx != -1:
                for l in self.listeners:
                    l([3, old_idx, new_idx, newrow])





class Select(Signal):
    def __init__(self, parent, select_sql):
        super().__init__(None)
        self.parent = parent
        self.select_sql = select_sql
        self.conn = self.parent.conn
        self.sql = f"SELECT {self.select_sql} FROM ({self.parent.sql})"
        self.parent.listeners.append(self.onevent)
        self.sql_from_row = f"SELECT {self.select_sql} FROM (SELECT {', '.join([f'? as {col}' for col in self.parent.columns])})"
        cursor = execute(self.conn, f"SELECT * FROM ({self.sql}) LIMIT 0", [])
        self.columns = [col[0] for col in cursor.description]
        self.deps = [self.parent]
        self.update = self.onevent
    
    def select_from_row(self, row):
        cursor = execute(self.conn, self.sql_from_row, row)
        return cursor.fetchone()

    def onevent(self, event):
        if event[0] < 3:
            row = self.select_from_row(event[1])
            for listener in self.listeners:
                listener([event[0], row])
        else:
            oldrow = self.select_from_row(event[1])
            newrow = self.select_from_row(event[2])
            if oldrow != newrow:
                for listener in self.listeners:
                    listener([3, oldrow, newrow])

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            self.parent.remove_listener(self.onevent)
            self.listeners = None

class Tables:
    def __init__(self, conn, dialect="sqlite"):
        self.conn = conn
        self.dialect = dialect
        self.tables = {}

    def _get(self, name):
        if name not in self.tables:
            self.tables[name] = ReactiveTable(self.conn, name)
        return self.tables[name]

    def executeone(self, sql, params):
        sql_strip = sql.strip()
        lsql = sql_strip.lower()
        if lsql.startswith("insert"):
            m = re.search(r"insert\s+(?:or\s+\w+\s+)?into\s+([^\s(]+)", sql_strip, re.I)
            if not m:
                raise ValueError(f"Couldn't parse INSERT statement {sql}")
            table = m.group(1)
            self._get(table).insert(sql, params)
        elif lsql.startswith("update"):
            m = re.search(r"update\s+([^\s]+)", sql_strip, re.I)
            if not m:
                raise ValueError(f"Couldn't parse UPDATE statement {sql}")
            table = m.group(1)
            self._get(table).update(sql, params)
        elif lsql.startswith("delete"):
            m = re.search(r"delete\s+from\s+([^\s]+)", sql_strip, re.I)
            if not m:
                raise ValueError(f"Couldn't parse DELETE statement {sql}")
            table = m.group(1)
            self._get(table).delete(sql, params)
        elif lsql.startswith("select"):
            from .reactive_sql import parse_reactive
            expr = sqlglot.parse_one(_convert_dot_sql(sql_strip), read=self.dialect)
            return parse_reactive(expr, self, params)
        else:
            raise ValueError(f"Unsupported SQL statement {sql}")

from .join import Join  # noqa: F401 - re-export for convenience
