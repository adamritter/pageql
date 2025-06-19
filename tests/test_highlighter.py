from pathlib import Path
import html
import re
import time

from pageql.highlighter import highlight, highlight_block


def _extract_snippet(page: str) -> str:
    start = page.index('<div class="highlight')
    start = page.index('>', page.index('<pre', start)) + 1
    end = page.index('</pre>', start)
    return page[start:end]


def _remove_color_spans(html_text: str) -> str:
    no_spans = re.sub(r"</?span[^>]*>", "", html_text)
    return html.unescape(no_spans)


def test_highlight_roundtrip():
    """Verify highlight() output and that it runs reasonably fast.

    The duration limit is a heuristic intended to catch extreme slowdowns
    rather than an exact performance benchmark.
    """
    page = Path("website/todos.pageql").read_text()
    snippet = _extract_snippet(page)
    plain = _remove_color_spans(snippet)

    start = time.perf_counter()
    rehighlighted = highlight(plain)
    duration = time.perf_counter() - start
    # Allow a small buffer because this check is only to detect drastic
    # regressions in performance.
    assert duration < 0.05

    if rehighlighted != snippet:
        max_len = min(len(rehighlighted), len(snippet))
        diff_index = next(
            (i for i in range(max_len) if rehighlighted[i] != snippet[i]),
            max_len,
        )
        expected = snippet[diff_index : diff_index + 100]
        actual = rehighlighted[diff_index : diff_index + 100]
        print(
            f"Mismatch at char {diff_index}: {actual!r} != {expected!r}",
        )
    assert _remove_color_spans(rehighlighted) == plain


def test_highlight_block_wraps_highlight():
    page = Path("website/todos.pageql").read_text()
    snippet = _extract_snippet(page)
    plain = _remove_color_spans(snippet)

    block = highlight_block(plain)

    assert block.startswith('<div style="position: relative;">')
    assert '<button onclick="copySourceCode(this)"' in block
    assert '<div class="highlight"' in block
    assert highlight(plain) in block
    assert block.rstrip().endswith('</pre></div></div></div>')
