from collections import Counter

from .reactive import execute, Signal


class Join(Signal):
    def __init__(self, parent1, parent2, on_sql, *, left_outer=False, right_outer=False):
        super().__init__(None)
        self.parent1 = parent1
        self.parent2 = parent2
        self.on_sql = on_sql
        self.left_outer = left_outer
        self.right_outer = right_outer
        self.conn = self.parent1.conn
        if self.left_outer and self.right_outer:
            join_kw = "FULL OUTER JOIN"
        elif self.left_outer:
            join_kw = "LEFT JOIN"
        elif self.right_outer:
            join_kw = "RIGHT JOIN"
        else:
            join_kw = "JOIN"
        self.sql = (
            f"SELECT * FROM ({self.parent1.sql}) AS a {join_kw} ({self.parent2.sql}) AS b ON {self.on_sql}"
        )
        self._cb1 = lambda e: self.onevent(e, 1)
        self._cb2 = lambda e: self.onevent(e, 2)
        self.parent1.listeners.append(self._cb1)
        self.parent2.listeners.append(self._cb2)
        self.columns = list(self.parent1.columns) + list(self.parent2.columns)
        if self.left_outer:
            self._null_right = tuple([None] * len(self.parent2.columns))
        if self.right_outer:
            self._null_left = tuple([None] * len(self.parent1.columns))
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

    def _cfg(self, side):
        if side == 1:
            return {
                "fetch_this": self._fetch_left,
                "fetch_other": self._fetch_right,
                "null_this": getattr(self, "_null_left", None),
                "null_other": getattr(self, "_null_right", None),
                "outer_this": self.left_outer,
                "outer_other": self.right_outer,
            }
        return {
            "fetch_this": self._fetch_right,
            "fetch_other": self._fetch_left,
            "null_this": getattr(self, "_null_right", None),
            "null_other": getattr(self, "_null_left", None),
            "outer_this": self.right_outer,
            "outer_other": self.left_outer,
        }

    def _combine(self, side, r1, r2):
        return r1 + r2 if side == 1 else r2 + r1

    def _insert_side(self, row, side):
        c = self._cfg(side)
        others = c["fetch_other"](row)
        if others:
            for other in others:
                if c["outer_other"]:
                    this_rows = c["fetch_this"](other)
                    if len(this_rows) == 1:
                        self._emit([
                            3,
                            self._combine(side, c["null_this"], other),
                            self._combine(side, row, other),
                        ])
                    else:
                        self._emit([1, self._combine(side, row, other)])
                else:
                    self._emit([1, self._combine(side, row, other)])
        elif c["outer_this"]:
            self._emit([1, self._combine(side, row, c["null_other"])])

    def _delete_side(self, row, side):
        c = self._cfg(side)
        others = c["fetch_other"](row)
        if others:
            for other in others:
                if c["outer_other"]:
                    remaining = c["fetch_this"](other)
                    if len(remaining) == 0:
                        self._emit([
                            3,
                            self._combine(side, row, other),
                            self._combine(side, c["null_this"], other),
                        ])
                    else:
                        self._emit([2, self._combine(side, row, other)])
                else:
                    self._emit([2, self._combine(side, row, other)])
        elif c["outer_this"]:
            self._emit([2, self._combine(side, row, c["null_other"])])

    def _update_side(self, oldrow, newrow, side):
        if oldrow == newrow:
            return
        c = self._cfg(side)
        old_other = c["fetch_other"](oldrow)
        new_other = c["fetch_other"](newrow)

        if c["outer_this"] and c["outer_other"]:
            old_set = set(old_other)
            new_set = set(new_other)

            for other in old_set & new_set:
                if self._combine(side, oldrow, other) != self._combine(side, newrow, other):
                    self._emit([
                        3,
                        self._combine(side, oldrow, other),
                        self._combine(side, newrow, other),
                    ])

            for other in old_set - new_set:
                remaining = c["fetch_this"](other)
                if len(remaining) == 0:
                    self._emit([
                        3,
                        self._combine(side, oldrow, other),
                        self._combine(side, c["null_this"], other),
                    ])
                else:
                    self._emit([2, self._combine(side, oldrow, other)])

            for other in new_set - old_set:
                total = len(c["fetch_this"](other))
                if total == 1:
                    self._emit([
                        3,
                        self._combine(side, c["null_this"], other),
                        self._combine(side, newrow, other),
                    ])
                else:
                    self._emit([1, self._combine(side, newrow, other)])

            if not old_other and not new_other:
                if oldrow != newrow:
                    self._emit([
                        3,
                        self._combine(side, oldrow, c["null_other"]),
                        self._combine(side, newrow, c["null_other"]),
                    ])
            elif not old_other and new_other:
                self._emit([2, self._combine(side, oldrow, c["null_other"])])
            elif old_other and not new_other:
                self._emit([1, self._combine(side, newrow, c["null_other"])])
            return

        if c["outer_other"]:
            old_set = set(old_other)
            new_set = set(new_other)

            for other in old_set & new_set:
                if self._combine(side, oldrow, other) != self._combine(side, newrow, other):
                    self._emit([
                        3,
                        self._combine(side, oldrow, other),
                        self._combine(side, newrow, other),
                    ])

            for other in old_set - new_set:
                remaining = c["fetch_this"](other)
                if len(remaining) == 0:
                    self._emit([
                        3,
                        self._combine(side, oldrow, other),
                        self._combine(side, c["null_this"], other),
                    ])
                else:
                    self._emit([2, self._combine(side, oldrow, other)])

            for other in new_set - old_set:
                total = len(c["fetch_this"](other))
                if total == 1:
                    self._emit([
                        3,
                        self._combine(side, c["null_this"], other),
                        self._combine(side, newrow, other),
                    ])
                else:
                    self._emit([1, self._combine(side, newrow, other)])
            return

        if c["outer_this"]:
            if not old_other:
                old_other = [c["null_other"]]
            if not new_other:
                new_other = [c["null_other"]]

        old_counts = Counter(old_other)
        new_counts = Counter(new_other)

        for other, old_cnt in old_counts.items():
            new_cnt = new_counts.get(other, 0)
            for _ in range(min(old_cnt, new_cnt)):
                if self._combine(side, oldrow, other) != self._combine(side, newrow, other):
                    self._emit([
                        3,
                        self._combine(side, oldrow, other),
                        self._combine(side, newrow, other),
                    ])
            if old_cnt > new_cnt:
                for _ in range(old_cnt - new_cnt):
                    self._emit([2, self._combine(side, oldrow, other)])

        for other, new_cnt in new_counts.items():
            old_cnt = old_counts.get(other, 0)
            if new_cnt > old_cnt:
                for _ in range(new_cnt - old_cnt):
                    self._emit([1, self._combine(side, newrow, other)])

    def _insert_left(self, row):
        self._insert_side(row, 1)

    def _insert_right(self, row):
        self._insert_side(row, 2)

    def _delete_left(self, row):
        self._delete_side(row, 1)

    def _delete_right(self, row):
        self._delete_side(row, 2)

    def _update_left(self, oldrow, newrow):
        self._update_side(oldrow, newrow, 1)

    def _update_right(self, oldrow, newrow):
        self._update_side(oldrow, newrow, 2)


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

