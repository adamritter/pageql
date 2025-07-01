from pathlib import Path
import html
import re
import time

from pageql.highlighter import highlight, highlight_block


def _remove_color_spans(html_text: str) -> str:
    no_spans = re.sub(r"</?span[^>]*>", "", html_text)
    return html.unescape(no_spans)


def test_highlight_roundtrip():
    """Verify highlight() output and that it runs reasonably fast."""

    source = Path("website/todos.pageql").read_text()

    start = time.perf_counter()
    highlighted = highlight(source)
    duration = time.perf_counter() - start
    # Allow a small buffer because this check is only to detect drastic
    # regressions in performance.
    assert duration < 0.05

    assert _remove_color_spans(highlighted) == source
    assert highlight(source) == highlighted


def test_highlight_block_wraps_highlight():
    source = Path("website/todos.pageql").read_text()

    block = highlight_block(source)

    assert block.startswith('<div style="position: relative;">')
    assert '<button onclick="copySourceCode(this)"' in block
    assert '<div class="highlight"' in block
    assert highlight(source) in block
    assert block.rstrip().endswith('</pre></div></div></div>')


def test_highlight_closing_tag_slash():
    result = highlight("</h1>")
    assert '<span style="color: #808080;">/</span>' in result


def test_highlight_sql_comment():
    source = "{%let x=1 -- comment\n%}"
    result = highlight(source)
    assert '-- comment' in result
    assert '#6a9955' in result
    assert _remove_color_spans(result) == source
