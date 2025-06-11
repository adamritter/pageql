import sys
import types
import pytest

# Ensure watchfiles awatch stub to avoid dependency
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *a, **k: None
sys.path.insert(0, "src")

from pageql.github_auth import build_authorization_url, fetch_github_user


def test_build_authorization_url():
    url = build_authorization_url(
        "cid",
        "http://localhost/cb",
        state="s123",
        scope="read:user",
    )
    assert url.startswith("https://github.com/login/oauth/authorize")
    assert "client_id=cid" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%2Fcb" in url
    assert "state=s123" in url


@pytest.mark.anyio
async def test_fetch_github_user(monkeypatch):
    calls = {}

    class DummyResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    async def fetch_token(self, url, code=None, client_secret=None):
        calls["token_url"] = url
        calls["code"] = code
        return {"access_token": "t"}

    async def get(self, url, headers=None):
        calls["user_url"] = url
        return DummyResponse({"login": "octocat"})

    monkeypatch.setattr(
        fetch_github_user.__globals__["AsyncOAuth2Client"],
        "fetch_token",
        fetch_token,
    )
    monkeypatch.setattr(
        fetch_github_user.__globals__["AsyncOAuth2Client"],
        "get",
        get,
    )

    user = await fetch_github_user(
        client_id="cid",
        client_secret="secret",
        code="code",
        redirect_uri="http://localhost/cb",
    )

    assert calls["token_url"].endswith("access_token")
    assert calls["code"] == "code"
    assert calls["user_url"].endswith("/user")
    assert user == {"login": "octocat"}
