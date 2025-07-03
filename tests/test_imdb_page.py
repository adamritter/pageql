import sys
sys.path.insert(0, "src")

from pathlib import Path
import sqlite3
import tempfile
from pageql.pageql import PageQL
from pageql.parser import tokenize, build_ast


def test_imdb_attach_parsed():
    src = Path("website/imdb.pageql").read_text()
    tokens = tokenize(src)
    body, _ = build_ast(tokens, dialect="sqlite")
    assert ("#attach", "database '/opt/imdb.db' as imdb") in body


def test_imdb_people_listing(tmp_path):
    db_path = "/opt/imdb.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS people (person_id TEXT PRIMARY KEY, name TEXT, born INTEGER, died INTEGER)")
    conn.execute("INSERT OR REPLACE INTO people(person_id,name,born,died) VALUES ('p1','Alice',1980,NULL)")
    conn.commit()
    conn.close()

    src = Path("website/imdb.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("imdb", src)
    result = r.render("/imdb/people", http_verb="GET", reactive=False)
    body = result.body
    assert "Alice" in body

