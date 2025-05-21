import sys
from pathlib import Path
import types
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL


def test_unknown_directive_raises():
    r = PageQL(":memory:")
    r.load_module("bad", "{{#a }}")
    with pytest.raises(ValueError) as exc:
        r.render("/bad")
    assert "Unknown directive '#a'" in str(exc.value)
