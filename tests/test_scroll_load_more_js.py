from pathlib import Path


def test_scroll_page_has_no_helper_call():
    src = Path("website/infinite_scroll_infinite.pageql").read_text()
    assert "maybe_load_more(document.body, 0)" not in src
