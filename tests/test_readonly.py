import pytest
from pageql.pageql import PageQL


def test_from_row_columns_readonly():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.execute("INSERT INTO items(name) VALUES ('x')")
    r.load_module("m", "{%from items%}{%let id = 2%}{%endfrom%}")
    with pytest.raises(ValueError):
        r.render("/m")


def test_param_allows_readonly_value():
    r = PageQL(":memory:")
    r.db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    r.db.execute("INSERT INTO items(name) VALUES ('x')")
    r.load_module(
        "m",
        "{%from items%}{%param id type=integer%}{{:id}}{%endfrom%}",
    )
    assert r.render("/m", reactive=False).body.strip() == "1"
