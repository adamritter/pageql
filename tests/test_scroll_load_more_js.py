from pathlib import Path


def test_scroll_script_has_core_logic():
    src = Path("website/infinite_scroll_infinite.pageql").read_text()
    assert "addEventListener('scroll'" in src
    assert "console.log('load more')" in src
    assert "canLoadMore = false" in src
