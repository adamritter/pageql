import asyncio
from pathlib import Path
import tempfile

from pageql.http_utils import _http_get
from pageql import jws_serialize_compact, jws_deserialize_compact
from playwright_helpers import run_server_in_task
import json
import re


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

        m = re.search(r"state=([^\"]+)", body)
        assert m is not None
        token = m.group(1)
        data = json.loads(jws_deserialize_compact(token).decode())
        assert data["ongoing"] == 1
        assert data["path"] == "/githubauth"


def test_githubauth_callback_fetch(monkeypatch):
    src = Path("website/githubauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "githubauth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            from pageql import pageql as pql_mod
            seen = []

            def fake_fetch(url: str, headers=None):
                seen.append((url, headers))
                if "api.github.com/user" in url:
                    return {
                        "status_code": 200,
                        "headers": [],
                        "body": '{"login": "octocat"}',
                    }
                return {
                    "status_code": 200,
                    "headers": [],
                    "body": 'access_token=t&token_type=bearer&scope=',
                }

            old_fetch = pql_mod.fetch_sync
            pql_mod.fetch_sync = fake_fetch
            monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
            try:
                server, task, port = await run_server_in_task(tmpdir)
                state = jws_serialize_compact('{"ongoing":1,"path":"/githubauth"}')
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/githubauth/callback?code=abc&state={state}"
                )
                server.should_exit = True
                await task
            finally:
                pql_mod.fetch_sync = old_fetch
            return status, body.decode(), seen, state

        status, body, urls, state = asyncio.run(run_test())

        assert status == 200
        assert "access_token" in body
        assert "octocat" in body
        (token_url, token_headers), (user_url, user_headers) = urls
        assert token_url.startswith("https://github.com/login/oauth/access_token")
        assert "Iv23liGYF2X5uR4izdC3" in token_url
        assert "client_secret=secret" in token_url
        assert "code=abc" in token_url
        assert f"state={state}" in token_url
        assert user_url == "https://api.github.com/user"
        assert user_headers == {"Authorization": "Bearer t"}

