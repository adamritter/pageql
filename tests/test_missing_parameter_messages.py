import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
import sqlglot

from pageql.database import evalone
from pageql.reactive_sql import _replace_placeholders


def test_evalone_missing_param_message():
    conn = sqlite3.connect(":memory:")
    with pytest.raises(ValueError) as excinfo:
        evalone(conn, ":foo", {})
    msg = str(excinfo.value)
    assert "Missing parameter 'foo'" in msg
    assert "Available parameters" not in msg


def test_replace_placeholders_missing_param_message():
    expr = sqlglot.parse_one("SELECT :a + :b", read="sqlite")
    with pytest.raises(ValueError) as excinfo:
        _replace_placeholders(expr, {"a": 1}, "sqlite")
    msg = str(excinfo.value)
    assert "Missing parameter(s) b" in msg
    assert "Available parameters" not in msg
