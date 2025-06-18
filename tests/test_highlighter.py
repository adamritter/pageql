from pathlib import Path
import html
import re
import time

from pageql.highlighter import highlight


def _extract_snippet(page: str) -> str:
    start = page.index('<div class="highlight')
    start = page.index('>', page.index('<pre', start)) + 1
    end = page.index('</pre>', start)
    return page[start:end]


def _remove_color_spans(html_text: str) -> str:
    no_spans = re.sub(r"</?span[^>]*>", "", html_text)
    return html.unescape(no_spans)


def test_highlight_roundtrip():
    page = Path("website/todos.pageql").read_text()
    snippet = _extract_snippet(page)
    plain = _remove_color_spans(snippet)

    start = time.perf_counter()
    rehighlighted = highlight(plain)
    duration = time.perf_counter() - start
    assert duration < 0.01

    assert rehighlighted[:200] == snippet[:200]
