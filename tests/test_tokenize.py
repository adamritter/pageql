import sys
import types

sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

import pytest

from pageql.parser import tokenize


def test_unmatched_braces():
    with pytest.raises(SyntaxError) as exc:
        tokenize(
            "something like {{#a\n{{#let active_count =    COUNT(*) from todos WHERE completed = 0}}"
        )
    assert "mismatched {{ in token" in str(exc.value)


def test_tokenize_skip_comments():
    assert tokenize("Hello {{! comment }}World") == [
        ("text", "Hello "),
        ("text", "World"),
    ]


def test_tokenize_skip_block_comments_with_braces():
    assert tokenize("Hello {{!-- comment with }} braces --}}World") == [
        ("text", "Hello "),
        ("text", "World"),
    ]
