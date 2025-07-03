import sys
sys.path.insert(0, 'src')

from pageql.pageql import PageQL, _row_hash


def setup_items(r):
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])


def test_dump_directive_reactive_inserts():
    r = PageQL(':memory:')
    setup_items(r)
    r.load_module('m', '{%reactive on%}{%dump items%}')
    result = r.render('/m')
    ctx = result.context

    h1 = _row_hash((1, 'a'))
    h2 = _row_hash((2, 'b'))
    expected = (
        '<table>'
        '<th>id</th><th>name</th></tr>'
        f"<script>pstart(0)</script>"
        f"<script>pstart('0_{h1}')</script><tr><td>1</td><td>a</td></tr><script>pend('0_{h1}')</script>"
        f"<script>pstart('0_{h2}')</script><tr><td>2</td><td>b</td></tr><script>pend('0_{h2}')</script>"
        f"<script>pend(0)</script>"
        '</table>'
    )
    assert result.body.startswith(expected)

    r.tables.executeone("INSERT INTO items(name) VALUES ('c')", {})
    assert any('pinsert' in s for s in ctx.scripts)
