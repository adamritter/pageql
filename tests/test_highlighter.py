from pathlib import Path
import time

from pageql.highlighter import highlight


def _extract_snippet(html: str) -> str:
    start = html.index('<div class="highlight')
    start = html.index('>', html.index('<pre', start)) + 1
    end = html.index('</pre>', start)
    return html[start:end]


def test_highlight_matches_example():
    src = Path('examples/templates/todos.pageql').read_text()
    start = time.perf_counter()
    result = highlight(src)
    duration = time.perf_counter() - start
    assert duration < 0.01

    website = Path('website/todos.pageql').read_text()
    snippet = _extract_snippet(website)

    assert result[:200] == snippet[:200]
