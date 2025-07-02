import sys
sys.path.insert(0, "src")

from pageql.pageql import PageQL

SNIPPET = (
    "{%reactive off%}"
    "{%header Content-Type 'application/json'%}"
    "{%create table if not exists todos ("
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "    text TEXT NOT NULL,"
    "    completed INTEGER DEFAULT 0 CHECK(completed IN (0,1))"
    ")%}"
    "["
    "{{{COALESCE(json_group_array("
    "    json_object('id', id, 'text', text, 'completed', completed)"
    "), '[]') from todos}}}"
    ","
    "["
    "{%from todos order by id%}"
    "{%if NOT :__first_row%},{%endif%}"
    "{\"id\":{{id}},\"text\":\"{{text}}\",\"completed\":{{completed}} }"
    "{%endfrom%}"
    "]"
    "]"
)

def test_json_page_outputs_array():
    r = PageQL(":memory:")
    r.load_module("json", SNIPPET)
    r.db.execute(
        "CREATE TABLE IF NOT EXISTS todos(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, completed INTEGER DEFAULT 0 CHECK(completed IN (0,1)))"
    )
    r.db.execute("INSERT INTO todos(text) VALUES ('task')")
    result = r.render("/json", reactive=False)
    assert ("Content-Type", "application/json") in result.headers
    assert result.body.strip() == '[[{"id":1,"text":"task","completed":0}],[{"id":1,"text":"task","completed":0 }\n]]'
