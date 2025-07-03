import asyncio
from pathlib import Path
import tempfile

from pageql.http_utils import _http_get
from pageql import jws_serialize_compact, jws_deserialize_compact
from playwright_helpers import run_server_in_task
import json
import re


def test_auth_page_renders_form_and_github(monkeypatch):
    src = Path("website/auth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "auth.pageql").write_text(src, encoding="utf-8")
        monkeypatch.setenv("GITHUB_CLIENT_ID", "Iv23liGYF2X5uR4izdC3")

        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            status, _headers, body = await _http_get(f"http://127.0.0.1:{port}/auth")
            server.should_exit = True
            await task
            return status, body.decode()

        status, body = asyncio.run(run_test())

        assert status == 200
        assert "github.com/login/oauth/authorize" in body
        assert "Iv23liGYF2X5uR4izdC3" in body
        assert "/auth/login" in body

        m = re.search(r"state=([^\"]+)", body)
        assert m is not None
        token = m.group(1)
        data = json.loads(jws_deserialize_compact(token).decode())
        assert data["ongoing"] == 1
        assert data["path"] == "/auth"


def test_auth_github_callback_fetch(monkeypatch):
    src = Path("website/auth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "auth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            from pageql import pageql as pql_mod
            seen = []

            async def fake_fetch(url: str, headers=None, method="GET", body=None, **kwargs):
                seen.append((url, headers, method))
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

            old_fetch = pql_mod.fetch
            pql_mod.fetch = fake_fetch
            monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret")
            monkeypatch.setenv("GITHUB_CLIENT_ID", "Iv23liGYF2X5uR4izdC3")
            try:
                server, task, port = await run_server_in_task(tmpdir)
                state = jws_serialize_compact('{"ongoing":1,"path":"/auth"}')
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/auth/callback?code=abc&state={state}"
                )
                server.should_exit = True
                await task
            finally:
                pql_mod.fetch = old_fetch
            return status, body.decode(), seen, state

        status, body, urls, state = asyncio.run(run_test())

        assert status == 200
        assert "Loading token" in body
        assert "access_token" not in body
        assert "octocat" not in body
        (token_url, token_headers, token_method), (user_url, user_headers, user_method) = urls
        assert token_url.startswith("https://github.com/login/oauth/access_token")
        assert "Iv23liGYF2X5uR4izdC3" in token_url
        assert "client_secret=secret" in token_url
        assert "code=abc" in token_url
        assert f"state={state}" in token_url
        assert user_url == "https://api.github.com/user"
        assert user_headers == {
            "Authorization": "Bearer t",
            "User-Agent": "PageQL",
        }
        assert token_method == "GET"
        assert user_method == "GET"
