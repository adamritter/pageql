import os
from pageql.pageqlapp import PageQLApp
from pageql.reactive import execute


def test_connection_log_level(tmp_path, capsys):
    app = PageQLApp(':memory:', tmp_path, create_db=True, should_reload=False, log_level='debug')
    execute(app.conn, 'select 1', [])
    out = capsys.readouterr().out.lower()
    assert 'sql: select 1' in out
