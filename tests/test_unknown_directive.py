import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pageql.pageql import PageQL


def test_unknown_directive_raises():
    r = PageQL(":memory:")
    r.load_module("bad", "{%a %}")
    with pytest.raises(ValueError) as exc:
        r.render("/bad")
    assert "Unknown directive '#a'" in str(exc.value)


def test_from_directive_with_zero_width_space():
    r = PageQL(":memory:")
    bad = "{%from\u200b todos%}{%endfrom%}"
    r.load_module("bad_space", bad)
    with pytest.raises(ValueError) as exc:
        r.render("/bad_space")
    assert "Unknown directive '#from\u200b'" in str(exc.value)
