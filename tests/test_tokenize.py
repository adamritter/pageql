import sys

sys.path.insert(0, "src")

import pytest

from pageql.parser import tokenize


def test_unmatched_braces():
    assert tokenize(
        "something like {%a\n{%let active_count =    COUNT(*) from todos WHERE completed = 0%}"
    ) == [
        ("text", "something like "),
        ("#a", "{%let active_count =    COUNT(*) from todos WHERE completed = 0"),
    ]


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


def test_tokenize_sql_comment_in_directive():
    assert tokenize("{%let x=1 -- comment\n%}") == [
        ("#let", "x=1"),
    ]


def test_tokenize_joined_directives():
    assert tokenize("{%param a; param b%}") == [
        ("#param", "a"),
        ("#param", "b"),
    ]


def test_tokenize_end_space_directives():
    assert tokenize("{%from items%}{%end from%}") == [
        ("#from", "items"),
        ("#endfrom", None),
    ]
    assert tokenize("{%partial x%}{%end partial%}") == [
        ("#partial", "x"),
        ("#endpartial", None),
    ]
    assert tokenize("{%if 1%}a{%end if%}") == [
        ("#if", "1"),
        ("text", "a"),
        ("#endif", None),
    ]
