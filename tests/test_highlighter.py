from pathlib import Path
import time

from pageql.highlighter import highlight, highlight_block


def _extract_snippet(html: str) -> str:
    start = html.index('<div class="highlight')
    start = html.index('>', html.index('<pre', start)) + 1
    end = html.index('</pre>', start)
    return html[start:end]


def _extract_block(html: str) -> str:
    start = html.index('<div style="position: relative;">')
    end_pre = html.index('</pre>', start)
    end1 = html.index('</div>', end_pre)
    end2 = html.index('</div>', end1 + 6)
    end3 = html.index('</div>', end2 + 6)
    return html[start:end3 + 6]


def test_highlight_matches_example():
    src = Path('examples/templates/todos.pageql').read_text()
    start = time.perf_counter()
    result = highlight(src)
    duration = time.perf_counter() - start
    assert duration < 0.01

    website = Path('website/todos.pageql').read_text()
    snippet = _extract_snippet(website)

    assert result[:200] == snippet[:200]


def test_highlight_block_matches_example():
    src = Path('examples/templates/todos.pageql').read_text()
    result = highlight_block(src)

    website = Path('website/todos.pageql').read_text()
    block = _extract_block(website)

    assert result[:200] == block[:200]
