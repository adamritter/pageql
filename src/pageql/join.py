from collections import Counter

from .reactive import execute, Signal


class Join(Signal):
    def __init__(self, parent1, parent2, on_sql):
        super().__init__(None)
        self.parent1 = parent1
        self.parent2 = parent2
        self.on_sql = on_sql
        self.conn = self.parent1.conn
        self.sql = (
            f"SELECT * FROM ({self.parent1.sql}) AS a JOIN ({self.parent2.sql}) AS b ON {self.on_sql}"
        )
        self._cb1 = lambda e: self.onevent(e, 1)
        self._cb2 = lambda e: self.onevent(e, 2)
        self.parent1.listeners.append(self._cb1)
        self.parent2.listeners.append(self._cb2)
        self.columns = list(self.parent1.columns) + list(self.parent2.columns)
        self.deps = [self.parent1, self.parent2]

        left_cols = ", ".join([f"? as {c}" for c in self.parent1.columns])
        right_cols = ", ".join([f"? as {c}" for c in self.parent2.columns])
        self.match_sql = (
            f"SELECT 1 FROM (SELECT {left_cols}) AS a JOIN (SELECT {right_cols}) AS b ON {self.on_sql}"
        )

        self.fetch_right_sql = (
            f"SELECT b.* FROM (SELECT {left_cols}) AS a JOIN ({self.parent2.sql}) AS b ON {self.on_sql}"
        )

        self.fetch_left_sql = (
            f"SELECT a.* FROM ({self.parent1.sql}) AS a JOIN (SELECT {right_cols}) AS b ON {self.on_sql}"
        )


    def _emit(self, event):
        for listener in self.listeners:
            listener(event)

    def _match(self, r1, r2):
        cursor = execute(self.conn, self.match_sql, list(r1) + list(r2))
        return cursor.fetchone() is not None

    def _fetch_right(self, r1):
        cur = execute(self.conn, self.fetch_right_sql, list(r1))
        return list(cur.fetchall())

    def _fetch_left(self, r2):
        cur = execute(self.conn, self.fetch_left_sql, list(r2))
        return list(cur.fetchall())

    def _insert_left(self, row):
        for r2 in self._fetch_right(row):
            self._emit([1, row + r2])

    def _insert_right(self, row):
        for r1 in self._fetch_left(row):
            self._emit([1, r1 + row])

    def _delete_left(self, row):
        for r2 in self._fetch_right(row):
            self._emit([2, row + r2])

    def _delete_right(self, row):
        for r1 in self._fetch_left(row):
            self._emit([2, r1 + row])

    def _update_left(self, oldrow, newrow):
        if oldrow == newrow:
            return
        old_matches = self._fetch_right(oldrow)
        new_matches = self._fetch_right(newrow)

        old_counts = Counter(old_matches)
        new_counts = Counter(new_matches)

        for r2, old_cnt in old_counts.items():
            new_cnt = new_counts.get(r2, 0)
            for _ in range(min(old_cnt, new_cnt)):
                if oldrow + r2 != newrow + r2:
                    self._emit([3, oldrow + r2, newrow + r2])
            if old_cnt > new_cnt:
                for _ in range(old_cnt - new_cnt):
                    self._emit([2, oldrow + r2])

        for r2, new_cnt in new_counts.items():
            old_cnt = old_counts.get(r2, 0)
            if new_cnt > old_cnt:
                for _ in range(new_cnt - old_cnt):
                    self._emit([1, newrow + r2])

    def _update_right(self, oldrow, newrow):
        if oldrow == newrow:
            return
        old_matches = self._fetch_left(oldrow)
        new_matches = self._fetch_left(newrow)

        old_counts = Counter(old_matches)
        new_counts = Counter(new_matches)

        for r1, old_cnt in old_counts.items():
            new_cnt = new_counts.get(r1, 0)
            for _ in range(min(old_cnt, new_cnt)):
                if r1 + oldrow != r1 + newrow:
                    self._emit([3, r1 + oldrow, r1 + newrow])
            if old_cnt > new_cnt:
                for _ in range(old_cnt - new_cnt):
                    self._emit([2, r1 + oldrow])

        for r1, new_cnt in new_counts.items():
            old_cnt = old_counts.get(r1, 0)
            if new_cnt > old_cnt:
                for _ in range(new_cnt - old_cnt):
                    self._emit([1, r1 + newrow])

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

    def remove_listener(self, listener):
        """Remove *listener* and detach from parents when unused."""
        if listener in self.listeners:
            self.listeners.remove(listener)
        if not self.listeners:
            for parent, cb in ((self.parent1, self._cb1), (self.parent2, self._cb2)):
                parent.remove_listener(cb)
            self.listeners = None

