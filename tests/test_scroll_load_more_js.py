import sys
sys.path.insert(0, "src")

from pathlib import Path
from pageql.parser import tokenize, build_ast


def _has_infinite_from(nodes):
    for node in nodes:
        if isinstance(node, list):
            if node[0] == "#from" and len(node) > 4 and node[4] is True:
                return True
            for item in node:
                if isinstance(item, list) and _has_infinite_from([item]):
                    return True
    return False


def test_scroll_page_has_no_helper_call():
    src = Path("website/infinite_scroll_infinite.pageql").read_text()
    tokens = tokenize(src)
    body, _ = build_ast(tokens, dialect="sqlite")
    assert _has_infinite_from(body)
