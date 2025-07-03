import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageql.database import connect_database
from pageql.pageql import PageQL


def test_connect_database_returns_dialect():
    conn, dialect = connect_database(":memory:")
    assert dialect == "sqlite"
    conn.close()


def test_pageql_stores_dialect():
    p = PageQL(":memory:")
    assert p.dialect == "sqlite"
    p.db.close()


def test_connect_database_enables_foreign_keys():
    conn, _ = connect_database(":memory:")
    val = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.close()
    assert val == 1
