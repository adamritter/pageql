from .reactive import execute


class Join:
    def __init__(self, parent1, parent2, on_sql):
        self.parent1 = parent1
        self.parent2 = parent2
        self.on_sql = on_sql
        self.listeners = []
        self.conn = self.parent1.conn
        self.sql = (
            f"SELECT * FROM ({self.parent1.sql}) AS a JOIN ({self.parent2.sql}) AS b ON {self.on_sql}"
        )
        self._l1 = lambda e: self.onevent(e, 1)
        self._l2 = lambda e: self.onevent(e, 2)
        self.parent1.listeners.append(self._l1)
        self.parent2.listeners.append(self._l2)
        self.columns = list(self.parent1.columns) + list(self.parent2.columns)

        left_cols = ", ".join([f"? as {c}" for c in self.parent1.columns])
        right_cols = ", ".join([f"? as {c}" for c in self.parent2.columns])
        self.match_sql = (
            f"SELECT 1 FROM (SELECT {left_cols}) AS a JOIN (SELECT {right_cols}) AS b ON {self.on_sql}"
        )

        self.rows1 = list(self.conn.execute(self.parent1.sql).fetchall())
        self.rows2 = list(self.conn.execute(self.parent2.sql).fetchall())

        self._counts = {}
        for r1 in self.rows1:
            for r2 in self.rows2:
                if self._match(r1, r2):
                    row = r1 + r2
                    self._counts[row] = self._counts.get(row, 0) + 1

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

    def _match(self, r1, r2):
        cursor = execute(self.conn, self.match_sql, list(r1) + list(r2))
        return cursor.fetchone() is not None

    def _insert_left(self, row):
        self.rows1.append(row)
        for r2 in self.rows2:
            if self._match(row, r2):
                res = row + r2
                prev = self._counts.get(res, 0)
                self._counts[res] = prev + 1
                if prev == 0:
                    self._emit([1, res])

    def _insert_right(self, row):
        self.rows2.append(row)
        for r1 in self.rows1:
            if self._match(r1, row):
                res = r1 + row
                prev = self._counts.get(res, 0)
                self._counts[res] = prev + 1
                if prev == 0:
                    self._emit([1, res])

    def _delete_left(self, row):
        try:
            self.rows1.remove(row)
        except ValueError:
            return
        for r2 in self.rows2:
            if self._match(row, r2):
                res = row + r2
                prev = self._counts.get(res, 0)
                if prev <= 1:
                    if res in self._counts:
                        del self._counts[res]
                    if prev == 1:
                        self._emit([2, res])
                else:
                    self._counts[res] = prev - 1

    def _delete_right(self, row):
        try:
            self.rows2.remove(row)
        except ValueError:
            return
        for r1 in self.rows1:
            if self._match(r1, row):
                res = r1 + row
                prev = self._counts.get(res, 0)
                if prev <= 1:
                    if res in self._counts:
                        del self._counts[res]
                    if prev == 1:
                        self._emit([2, res])
                else:
                    self._counts[res] = prev - 1

    def _update_left(self, oldrow, newrow):
        idx = self.rows1.index(oldrow)
        self.rows1[idx] = newrow
        for r2 in self.rows2:
            old_match = self._match(oldrow, r2)
            new_match = self._match(newrow, r2)
            oldres = oldrow + r2
            newres = newrow + r2
            if old_match and new_match:
                if oldres == newres:
                    continue
                prev_old = self._counts.get(oldres, 0)
                delete_event = False
                if prev_old > 0:
                    if prev_old == 1:
                        del self._counts[oldres]
                        delete_event = True
                    else:
                        self._counts[oldres] = prev_old - 1
                prev_new = self._counts.get(newres, 0)
                insert_event = False
                if prev_new == 0:
                    self._counts[newres] = 1
                    insert_event = True
                else:
                    self._counts[newres] = prev_new + 1
                if delete_event and insert_event:
                    self._emit([3, oldres, newres])
                elif delete_event:
                    self._emit([2, oldres])
                elif insert_event:
                    self._emit([1, newres])
            elif old_match and not new_match:
                prev = self._counts.get(oldres, 0)
                if prev <= 1:
                    if oldres in self._counts:
                        del self._counts[oldres]
                    if prev == 1:
                        self._emit([2, oldres])
                else:
                    self._counts[oldres] = prev - 1
            elif not old_match and new_match:
                prev = self._counts.get(newres, 0)
                self._counts[newres] = prev + 1
                if prev == 0:
                    self._emit([1, newres])

    def _update_right(self, oldrow, newrow):
        idx = self.rows2.index(oldrow)
        self.rows2[idx] = newrow
        for r1 in self.rows1:
            old_match = self._match(r1, oldrow)
            new_match = self._match(r1, newrow)
            oldres = r1 + oldrow
            newres = r1 + newrow
            if old_match and new_match:
                if oldres == newres:
                    continue
                prev_old = self._counts.get(oldres, 0)
                delete_event = False
                if prev_old > 0:
                    if prev_old == 1:
                        del self._counts[oldres]
                        delete_event = True
                    else:
                        self._counts[oldres] = prev_old - 1
                prev_new = self._counts.get(newres, 0)
                insert_event = False
                if prev_new == 0:
                    self._counts[newres] = 1
                    insert_event = True
                else:
                    self._counts[newres] = prev_new + 1
                if delete_event and insert_event:
                    self._emit([3, oldres, newres])
                elif delete_event:
                    self._emit([2, oldres])
                elif insert_event:
                    self._emit([1, newres])
            elif old_match and not new_match:
                prev = self._counts.get(oldres, 0)
                if prev <= 1:
                    if oldres in self._counts:
                        del self._counts[oldres]
                    if prev == 1:
                        self._emit([2, oldres])
                else:
                    self._counts[oldres] = prev - 1
            elif not old_match and new_match:
                prev = self._counts.get(newres, 0)
                self._counts[newres] = prev + 1
                if prev == 0:
                    self._emit([1, newres])

    def onevent(self, event, which):
        if which == 1:
            if event[0] == 1:
                self._insert_left(event[1])
            elif event[0] == 2:
                self._delete_left(event[1])
            else:
                self._update_left(event[1], event[2])
        else:
            if event[0] == 1:
                self._insert_right(event[1])
            elif event[0] == 2:
                self._delete_right(event[1])
            else:
                self._update_right(event[1], event[2])

