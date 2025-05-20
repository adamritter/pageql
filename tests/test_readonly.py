import pytest
from pageql.pageql import PageQL


def test_from_row_columns_readonly():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.execute("INSERT INTO items(name) VALUES ('x')")
    r.load_module("m", "{{#from items}}{{#set id 2}}{{/from}}")
    with pytest.raises(ValueError):
        r.render("/m")
