import sqlite3
import types

import pageql.reactive as reactive


def test_slow_query_warning(monkeypatch, capsys):
    conn = sqlite3.connect(':memory:')
    times = [0.0, 0.011]

    def fake_perf_counter():
        return times.pop(0)

    monkeypatch.setattr(reactive.time, 'perf_counter', fake_perf_counter)
    reactive.execute(conn, 'select 1', [])
    out = capsys.readouterr().out.lower()
    assert 'warning, slow query' in out
    assert 'select 1' in out
