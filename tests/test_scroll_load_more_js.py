from pathlib import Path


def test_scroll_script_calls_helper():
    src = Path("website/infinite_scroll_infinite.pageql").read_text()
    assert "maybe_load_more(document.body, 0)" in src
