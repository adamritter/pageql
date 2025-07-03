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
