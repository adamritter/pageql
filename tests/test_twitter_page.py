import sys
sys.path.insert(0, "src")

from pathlib import Path
from pageql.pageql import PageQL


def test_twitter_post_and_render():
    src = Path("website/twitter/index.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("twitter/index", src)
    r.render("/twitter/index", reactive=False)  # create tables

    r.render("/twitter/index", params={"username": "alice", "text": "hello"}, partial="tweet", http_verb="POST")

    result = r.render("/twitter/index", reactive=False)
    body = result.body
    assert "alice" in body
    assert "hello" in body


def test_twitter_follow_filter():
    src = Path("website/twitter/index.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("twitter/index", src)
    r.render("/twitter/index", reactive=False)

    r.render(
        "/twitter/index",
        params={"username": "alice", "text": "hello"},
        partial="tweet",
        http_verb="POST",
    )
    r.render(
        "/twitter/index",
        params={"username": "bob", "text": "hi"},
        partial="tweet",
        http_verb="POST",
    )

    bob_id = r.db.execute("select id from users where username='bob'").fetchone()[0]

    result = r.render(
        "/twitter/index",
        params={"username": "alice", "filter": "following"},
        reactive=False,
    )
    assert "bob</strong>: hi" not in result.body

    r.render(
        "/twitter/index",
        params={"username": "alice", "filter": "all", "follow": bob_id},
        reactive=False,
    )

    result = r.render(
        "/twitter/index",
        params={"username": "alice", "filter": "following"},
        reactive=False,
    )
    assert "bob</strong>: hi" in result.body

    r.render(
        "/twitter/index",
        params={"username": "alice", "filter": "all", "unfollow": bob_id},
        reactive=False,
    )

    result = r.render(
        "/twitter/index",
        params={"username": "alice", "filter": "following"},
        reactive=False,
    )
    assert "bob</strong>: hi" not in result.body
