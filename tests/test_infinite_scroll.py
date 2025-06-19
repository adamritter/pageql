import sys, types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pathlib import Path
from pageql.pageql import PageQL


def test_infinite_scroll_initial_numbers():
    src = Path("website/infinite_scroll.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("infinite_scroll", src)
    result = r.render("/infinite_scroll", reactive=False)
    assert "/infinite_scroll/numbers/200" in result.body
    assert result.body.count("<br>") == 100
