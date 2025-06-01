import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageql.pageql import connect_database, PageQL


def test_connect_database_returns_dialect():
    conn, dialect = connect_database(":memory:")
    assert dialect == "sqlite"
    conn.close()


def test_pageql_stores_dialect():
    p = PageQL(":memory:")
    assert p.dialect == "sqlite"
    p.db.close()
