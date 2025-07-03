import sqlite3
import pageql.reactive as reactive

def test_debug_sql_logging(capsys):
    conn = sqlite3.connect(':memory:')
    reactive.set_log_level(conn, 'debug')
    reactive.execute(conn, 'select 1', [])
    out = capsys.readouterr().out.lower()
    assert 'sql: select 1' in out
