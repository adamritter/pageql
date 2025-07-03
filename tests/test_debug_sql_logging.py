import sqlite3
import pageql.reactive as reactive

def test_debug_sql_logging(capsys):
    conn = sqlite3.connect(':memory:')
    reactive.execute(conn, 'select 1', [], log_level='debug')
    out = capsys.readouterr().out.lower()
    assert 'sql: select 1' in out
