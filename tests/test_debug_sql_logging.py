import sqlite3
import pageql.reactive as reactive

def test_debug_sql_logging(monkeypatch, capsys):
    conn = sqlite3.connect(':memory:')
    monkeypatch.setattr(reactive, 'LOG_LEVEL', 'debug')
    reactive.execute(conn, 'select 1', [])
    out = capsys.readouterr().out.lower()
    assert 'sql: select 1' in out
