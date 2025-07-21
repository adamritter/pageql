import sys
sys.path.insert(0, "src")

from pathlib import Path
from pageql.pageql import PageQL
import re


def extract_tweets(body: str) -> str:
    match = re.search(r'<ul id="tweets">(.*?)</ul>', body, re.S)
    assert match is not None
    return match.group(1)


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

def test_twitter_filter_links_present():
    src = Path("website/twitter/index.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("twitter/index", src)
    result = r.render("/twitter/index", reactive=False)
    body = result.body
    assert 'href="/twitter/index?filter=following' in body

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
    assert "bob</strong>: hi" not in extract_tweets(result.body)

    r.render(
        f"/twitter/index/follow/{bob_id}",
        params={"username": "alice"},
        http_verb="POST",
        reactive=False,
    )

    result = r.render(
        "/twitter/index",
        params={"username": "alice", "filter": "following"},
        reactive=False,
    )
    assert "bob</strong>: hi" in extract_tweets(result.body)

    r.render(
        f"/twitter/index/follow/{bob_id}",
        params={"username": "alice"},
        http_verb="DELETE",
        reactive=False,
    )

    result = r.render(
        "/twitter/index",
        params={"username": "alice", "filter": "following"},
        reactive=False,
    )
    assert "bob</strong>: hi" not in extract_tweets(result.body)

def test_twitter_follow_filter_reactive_anonymous():
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

    result = r.render(
        "/twitter/index",
        params={"filter": "following"},
        reactive=True,
    )
    assert "hello" not in extract_tweets(result.body)


def test_twitter_follow_button_updates():
    src = Path("website/twitter/index.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("twitter/index", src)
    r.render("/twitter/index", reactive=False)

    r.render(
        "/twitter/index",
        params={"username": "bob", "text": "hi"},
        partial="tweet",
        http_verb="POST",
    )
    bob_id = r.db.execute("select id from users where username='bob'").fetchone()[0]

    r.render(
        f"/twitter/index/follow/{bob_id}",
        params={"username": "alice"},
        http_verb="POST",
        reactive=False,
    )

    result = r.render(
        "/twitter/index",
        params={"username": "alice"},
        reactive=False,
    )

    assert 'hx-delete="/twitter/index/follow/' in result.body
    assert ">Unfollow</button>" in result.body


def test_twitter_username_selector_present():
    src = Path("website/twitter/index.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("twitter/index", src)
    result = r.render("/twitter/index", reactive=False)
    body = result.body
    assert '<input name="username"' in body
    assert 'list="usernames"' in body
    assert '<datalist id="usernames">' in body


def test_twitter_like_button_updates():
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

    tid = r.db.execute("select id from tweets where text='hello'").fetchone()[0]

    r.render(
        f"/twitter/index/like/{tid}",
        params={"username": "bob"},
        http_verb="POST",
        reactive=False,
    )

    result = r.render(
        "/twitter/index",
        params={"username": "bob"},
        reactive=False,
    )

    assert f'hx-delete="/twitter/index/like/{tid}"' in result.body
    assert '>♥</button> 1' in result.body

    r.render(
        f"/twitter/index/like/{tid}",
        params={"username": "bob"},
        http_verb="DELETE",
        reactive=False,
    )

    result = r.render(
        "/twitter/index",
        params={"username": "bob"},
        reactive=False,
    )

    assert f'hx-post="/twitter/index/like/{tid}"' in result.body
    assert '>♡</button> 0' in result.body


def test_twitter_dump_headers_not_duplicated():
    src = Path("website/twitter/index.pageql").read_text()
    r = PageQL(":memory:")
    r.load_module("twitter/index", src)
    result = r.render("/twitter/index", reactive=False)
    body = result.body

    assert "<h2>Tweets</h2>" not in body
    assert "<h2>Following</h2>" not in body
    assert body.count("<h2>Users</h2>") == 1

    assert "<h2>tweets</h2>" in body
    assert "<h2>following</h2>" in body
    assert "<h2>users</h2>" in body
