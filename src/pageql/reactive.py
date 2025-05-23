import re

def execute(conn, sql, params):
    try:
        cursor = conn.execute(sql, params)
    except Exception as e:
        raise Exception(f"Execute failed for query: {sql} with params: {params} with error: {e}")
    return cursor

from .join import Join


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

class ReactiveTable:
    def __init__(self, conn, table_name):
        self.conn = conn
        self.table_name = table_name
        self.listeners = []
        self.columns = [col[1] for col in self.conn.execute(f"PRAGMA table_info({self.table_name})")]
        self.sql = f"SELECT * FROM {self.table_name}"

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)

    def insert(self, sql, params):
        try:
            query = sql + " RETURNING *"
            cursor = self.conn.execute(query, params)
            row = cursor.fetchone()
        except Exception as e:
            raise Exception(f"Insert into table {self.table_name} failed for query: {query} with params: {params} with error: {e}")            
        for listener in self.listeners:
            listener([1, row])
            
    def delete(self, sql, params):
        """
        Delete rows **one by one**, notifying listeners after each deletion.
        """
        query = sql + " RETURNING * LIMIT 1"
        try:
            while True:
                cursor = self.conn.execute(query, params)
                row = cursor.fetchone()
                if row is None:
                    break
                for listener in self.listeners:
                    listener([2, row])
        except Exception as e:
            raise Exception(f"Delete from table {self.table_name} failed for query: {query} with params: {params} with error: {e}")

    def update(self, sql, params):
        """
        Update rows **one by one**, notifying listeners after each update.
        """
        m = re.search(r'update\s+([^\s]+)\s+set\s+(.*?)\s+where\s+(.*?);?\s*$', sql, re.I | re.S)
        if not m:
            raise ValueError(f"Couldn’t parse UPDATE statement {sql}")
        table, set_sql, where = m.groups()
        select_sql = f"SELECT * FROM {table} WHERE {where.rstrip()};"
        cursor = self.conn.execute(select_sql, params)
        rows = cursor.fetchall()
        update_sql = f"UPDATE {table} SET {set_sql} WHERE {' AND '.join([f'{k} IS :_col{index}' for index, k in enumerate(self.columns)])} RETURNING * LIMIT 1"
        params = params.copy()
        for row in rows:
            for index, value in enumerate(row):
                params[f"_col{index}"] = value
            cursor = self.conn.execute(update_sql, params)
            new_row = cursor.fetchone()
            if new_row is None:
                raise Exception(f"Update on table {self.table_name} failed for query: {update_sql} with params: {params}")
            if new_row == row:
                continue
            for listener in self.listeners:
                listener([3, row, new_row])
            
class Where:
    def __init__(self, parent, where_sql):
        self.parent = parent
        self.where_sql = where_sql
        self.listeners = []
        self.columns = self.parent.columns
        self.conn = self.parent.conn
        self.filter_sql = f"SELECT {', '.join([f'? as {col}' for col in self.columns])} WHERE {self.where_sql}"
        self.sql = f"SELECT * FROM ({self.parent.sql}) WHERE {self.where_sql}"
        self.parent.listeners.append(self.onevent)

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners and self.onevent in getattr(self.parent, "listeners", []):
            self.parent.listeners.remove(self.onevent)

    def contains_row(self, row):
        cursor = execute(self.conn, self.filter_sql, row)
        return cursor.fetchone() is not None
    
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

class CountAll:
    def __init__(self, parent):
        self.parent = parent
        self.listeners = []
        self.conn = self.parent.conn
        self.sql = f"SELECT COUNT(*) FROM ({self.parent.sql})"
        self.value = self.conn.execute(self.sql).fetchone()[0]
        self.parent.listeners.append(self.onevent)
        self.columns = "COUNT(*)"

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners and self.onevent in getattr(self.parent, "listeners", []):
            self.parent.listeners.remove(self.onevent)

    def onevent(self, event):
        oldvalue = self.value
        if event[0] == 1:
            self.value += 1
        elif event[0] == 2:
            self.value -= 1
        if oldvalue != self.value:
            for listener in self.listeners:
                listener([3, [oldvalue], [self.value]])

class DependentValue(Signal):
    """Wrap a reactive relation expected to yield a single-column row."""

    def __init__(self, parent):
        self.parent = parent
        self.conn = self.parent.conn
        self.sql = self.parent.sql
        cols = self.parent.columns
        if isinstance(cols, str):
            cols = [cols]
        if len(cols) != 1:
            raise ValueError("DependentValue parent must have exactly one column")
        self.columns = cols[0]
        row = self.conn.execute(self.sql).fetchone()
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
            raise ValueError("DependentValue parent must have exactly one column")

        self.columns = cols[0]
        parent.listeners.append(self.onevent)

        row = self.conn.execute(self.sql).fetchone()
        value = row[0] if row else None

        self.set_value(value)

    def onevent(self, event):
        if event[0] == 1:
            value = event[1][0]
        elif event[0] == 2:
            value = None
        else:
            value = event[2][0]
        self.set_value(value)

class UnionAll:
    def __init__(self, parent1, parent2):
        self.parent1 = parent1
        self.parent2 = parent2
        self.listeners = []
        self.conn = self.parent1.conn
        self.sql = f"SELECT * FROM ({self.parent1.sql}) UNION ALL SELECT * FROM ({self.parent2.sql})"
        self.parent1.listeners.append(self.onevent)
        self.parent2.listeners.append(self.onevent)
        self.columns = self.parent1.columns
        if self.parent1.columns != self.parent2.columns:
            raise ValueError(f"UnionAll: parent1 and parent2 must have the same columns {self.parent1.columns} != {self.parent2.columns}")

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            if self.onevent in getattr(self.parent1, "listeners", []):
                self.parent1.listeners.remove(self.onevent)
            if self.onevent in getattr(self.parent2, "listeners", []):
                self.parent2.listeners.remove(self.onevent)

    def onevent(self, event):
        for listener in self.listeners:
            listener(event)


class Union:
    def __init__(self, parent1, parent2):
        self.parent1 = parent1
        self.parent2 = parent2
        self.listeners = []
        self.conn = self.parent1.conn
        self.sql = f"SELECT * FROM ({self.parent1.sql}) UNION SELECT * FROM ({self.parent2.sql})"
        self.parent1.listeners.append(self.onevent)
        self.parent2.listeners.append(self.onevent)
        self.columns = self.parent1.columns
        if self.parent1.columns != self.parent2.columns:
            raise ValueError(
                f"Union: parent1 and parent2 must have the same columns {self.parent1.columns} != {self.parent2.columns}"
            )

        # Track how many times a row appears across parents
        self._counts = {}
        for row in self.conn.execute(self.parent1.sql).fetchall():
            self._counts[row] = self._counts.get(row, 0) + 1
        for row in self.conn.execute(self.parent2.sql).fetchall():
            self._counts[row] = self._counts.get(row, 0) + 1

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            if self.onevent in getattr(self.parent1, "listeners", []):
                self.parent1.listeners.remove(self.onevent)
            if self.onevent in getattr(self.parent2, "listeners", []):
                self.parent2.listeners.remove(self.onevent)

    def _emit(self, event):
        for listener in self.listeners:
            listener(event)

    def _insert(self, row):
        prev = self._counts.get(row, 0)
        self._counts[row] = prev + 1
        if prev == 0:
            self._emit([1, row])

    def _delete(self, row):
        prev = self._counts.get(row, 0)
        if prev == 1:
            del self._counts[row]
            self._emit([2, row])
        elif prev > 1:
            self._counts[row] = prev - 1

    def _update(self, oldrow, newrow):
        if oldrow == newrow:
            return
        delete_event = False
        insert_event = False
        oldcnt = self._counts.get(oldrow, 0)
        newcnt = self._counts.get(newrow, 0)

        if oldcnt > 0:
            if oldcnt == 1:
                del self._counts[oldrow]
                delete_event = True
            else:
                self._counts[oldrow] = oldcnt - 1

        if newcnt == 0:
            self._counts[newrow] = 1
            insert_event = True
        else:
            self._counts[newrow] = newcnt + 1

        if delete_event and insert_event:
            self._emit([3, oldrow, newrow])
        elif delete_event:
            self._emit([2, oldrow])
        elif insert_event:
            self._emit([1, newrow])

    def onevent(self, event):
        if event[0] == 1:
            self._insert(event[1])
        elif event[0] == 2:
            self._delete(event[1])
        else:
            self._update(event[1], event[2])


class Intersect:
    def __init__(self, parent1, parent2):
        self.parent1 = parent1
        self.parent2 = parent2
        self.listeners = []
        self.conn = self.parent1.conn
        self.sql = (
            f"SELECT * FROM ({self.parent1.sql}) INTERSECT SELECT * FROM ({self.parent2.sql})"
        )
        self._l1 = lambda e: self.onevent(e, 1)
        self._l2 = lambda e: self.onevent(e, 2)
        self.parent1.listeners.append(self._l1)
        self.parent2.listeners.append(self._l2)
        self.columns = self.parent1.columns
        if self.parent1.columns != self.parent2.columns:
            raise ValueError(
                f"Intersect: parent1 and parent2 must have the same columns {self.parent1.columns} != {self.parent2.columns}"
            )

        # Track counts per parent so duplicates from the same parent don't
        # result in duplicate intersection rows.
        self._counts1 = {}
        self._counts2 = {}
        for row in self.conn.execute(self.parent1.sql).fetchall():
            self._counts1[row] = self._counts1.get(row, 0) + 1
        for row in self.conn.execute(self.parent2.sql).fetchall():
            self._counts2[row] = self._counts2.get(row, 0) + 1

        # Set of rows currently present in the intersection
        self._rows = {
            row for row in self._counts1.keys() if self._counts2.get(row, 0) > 0
        }

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            if self._l1 in getattr(self.parent1, "listeners", []):
                self.parent1.listeners.remove(self._l1)
            if self._l2 in getattr(self.parent2, "listeners", []):
                self.parent2.listeners.remove(self._l2)

    def _emit(self, event):
        for listener in self.listeners:
            listener(event)

    def _insert(self, row, counts_self, counts_other):
        prev = counts_self.get(row, 0)
        counts_self[row] = prev + 1
        if prev == 0 and counts_other.get(row, 0) > 0 and row not in self._rows:
            self._rows.add(row)
            self._emit([1, row])

    def _delete(self, row, counts_self, counts_other):
        prev = counts_self.get(row, 0)
        if prev <= 1:
            if row in counts_self:
                del counts_self[row]
            if prev == 1 and counts_other.get(row, 0) > 0 and row in self._rows:
                self._rows.remove(row)
                self._emit([2, row])
        else:
            counts_self[row] = prev - 1

    def _update(self, oldrow, newrow, counts_self, counts_other):
        if oldrow == newrow:
            return

        old_in = oldrow in self._rows
        new_in = newrow in self._rows

        # Adjust counts
        oldcnt = counts_self.get(oldrow, 0)
        if oldcnt <= 1:
            if oldrow in counts_self:
                del counts_self[oldrow]
        else:
            counts_self[oldrow] = oldcnt - 1

        counts_self[newrow] = counts_self.get(newrow, 0) + 1

        old_after = counts_self.get(oldrow, 0) > 0 and counts_other.get(oldrow, 0) > 0
        new_after = counts_self.get(newrow, 0) > 0 and counts_other.get(newrow, 0) > 0

        if old_in and not old_after and oldrow in self._rows:
            self._rows.remove(oldrow)
        if not old_in and old_after:
            self._rows.add(oldrow)
        if new_in != new_after:
            if new_after:
                self._rows.add(newrow)
            else:
                self._rows.discard(newrow)

        removed = old_in and not old_after
        added = not new_in and new_after

        if removed and added:
            self._emit([3, oldrow, newrow])
        elif removed:
            self._emit([2, oldrow])
        elif added:
            self._emit([1, newrow])

    def onevent(self, event, which):
        if which == 1:
            counts_self = self._counts1
            counts_other = self._counts2
        else:
            counts_self = self._counts2
            counts_other = self._counts1

        if event[0] == 1:
            self._insert(event[1], counts_self, counts_other)
        elif event[0] == 2:
            self._delete(event[1], counts_self, counts_other)
        else:
            self._update(event[1], event[2], counts_self, counts_other)



class Select:
    def __init__(self, parent, select_sql):
        self.parent = parent
        self.select_sql = select_sql
        self.listeners = []
        self.conn = self.parent.conn
        self.sql = f"SELECT {self.select_sql} FROM ({self.parent.sql})"
        self.parent.listeners.append(self.onevent)
        self.sql_from_row = f"SELECT {self.select_sql} FROM (SELECT {', '.join([f'? as {col}' for col in self.parent.columns])})"
        cursor = self.conn.execute(f"SELECT * FROM ({self.sql}) LIMIT 0")
        self.columns = [col[0] for col in cursor.description]

    def remove_listener(self, listener):
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners and self.onevent in getattr(self.parent, "listeners", []):
            self.parent.listeners.remove(self.onevent)
    
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


class Tables:
    def __init__(self, conn):
        self.conn = conn
        self.tables = {}

    def _get(self, name):
        if name not in self.tables:
            self.tables[name] = ReactiveTable(self.conn, name)
        return self.tables[name]

    def executeone(self, sql, params):
        sql_strip = sql.strip()
        lsql = sql_strip.lower()
        if lsql.startswith("insert"):
            m = re.search(r"insert\s+into\s+([^\s(]+)", sql_strip, re.I)
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
            return parse_reactive(sql_strip, self, params)
        else:
            raise ValueError(f"Unsupported SQL statement {sql}")
