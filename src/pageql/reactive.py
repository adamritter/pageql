import re

class Signal:
    def __init__(self, value=None):
        self.value = value
        self.listeners = []
    
    def set(self, value):
        if self.value != value:
            self.value = value
            for listener in self.listeners:
                listener(value)

def execute(conn, sql, params):
    try:
        cursor = conn.execute(sql, params)
    except Exception as e:
        raise Exception(f"Execute failed for query: {sql} with params: {params} with error: {e}")
    return cursor


class DerivedSignal:
    def __init__(self, f, deps):
        self.f = f
        self.deps = deps
        self.value = f()
        self.listeners = []
        for dep in deps:
            dep.listeners.append(lambda _: self.update())
        
    def update(self):
        value = self.f()
        if self.value != value:
            self.value = value
            for listener in self.listeners:
                listener(value)

class ReactiveTable:
    def __init__(self, conn, table_name):
        self.conn = conn
        self.table_name = table_name
        self.listeners = []
        self.columns = [col[1] for col in self.conn.execute(f"PRAGMA table_info({self.table_name})")]
        self.sql = f"SELECT * FROM {self.table_name}"

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

    def onevent(self, event):
        oldvalue = self.value
        if event[0] == 1:
            self.value += 1
        elif event[0] == 2:
            self.value -= 1
        if oldvalue != self.value:
            for listener in self.listeners:
                listener([3, [oldvalue], [self.value]])

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
    
    def onevent(self, event):
        for listener in self.listeners:
            listener(event)

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