import asyncio
from pathlib import Path
import tempfile

from pageql.http_utils import _http_get
from playwright_helpers import run_server_in_task


def test_githubauth_page_renders_button():
    src = Path("website/githubauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "githubauth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            status, _headers, body = await _http_get(f"http://127.0.0.1:{port}/githubauth")
            server.should_exit = True
            await task
            return status, body.decode()

        status, body = asyncio.run(run_test())

        assert status == 200
        assert "github.com/login/oauth/authorize" in body
        assert "Iv23liGYF2X5uR4izdC3" in body


def test_githubauth_callback_fetch(monkeypatch):
    src = Path("website/githubauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "githubauth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            from pageql import pageql as pql_mod
            seen = []

            def fake_fetch(url: str, headers=None):
                seen.append(url)
                if "api.github.com/user" in url:
                    return {
                        "status_code": 200,
                        "headers": [],
                        "body": '{"login": "octocat"}',
                    }
                return {
                    "status_code": 200,
                    "headers": [],
                    "body": '{"access_token": "t"}',
                }

            old_fetch = pql_mod.fetch_sync
            pql_mod.fetch_sync = fake_fetch
            monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
            try:
                server, task, port = await run_server_in_task(tmpdir)
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/githubauth/callback?code=abc&state=xyz"
                )
                server.should_exit = True
                await task
            finally:
                pql_mod.fetch_sync = old_fetch
            return status, body.decode(), seen

        status, body, urls = asyncio.run(run_test())

        assert status == 200
        assert "access_token" in body
        assert "octocat" in body
        token_url, user_url = urls
        assert token_url.startswith("https://github.com/login/oauth/access_token")
        assert "Iv23liGYF2X5uR4izdC3" in token_url
        assert "client_secret=secret" in token_url
        assert "code=abc" in token_url
        assert "state=xyz" in token_url
        assert user_url.startswith("https://api.github.com/user?access_token=")

