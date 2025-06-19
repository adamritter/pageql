import asyncio
from pathlib import Path
import tempfile

from pageql.http_utils import _http_get
from pageql import jws_serialize_compact, jws_deserialize_compact
from playwright_helpers import run_server_in_task
import json
import re


def test_googleauth_page_renders_button(monkeypatch):
    src = Path("website/googleauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "googleauth.pageql").write_text(src, encoding="utf-8")
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "123456789.apps.googleusercontent.com")

        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            status, _headers, body = await _http_get(f"http://127.0.0.1:{port}/googleauth")
            server.should_exit = True
            await task
            return status, body.decode()

        status, body = asyncio.run(run_test())

        assert status == 200
        assert "accounts.google.com/o/oauth2/v2/auth" in body
        assert "123456789.apps.googleusercontent.com" in body

        m = re.search(r"state=([^\"]+)", body)
        assert m is not None
        token = m.group(1)
        data = json.loads(jws_deserialize_compact(token).decode())
        assert data["ongoing"] == 1
        assert data["path"] == "/googleauth"


def test_googleauth_callback_fetch(monkeypatch):
    src = Path("website/googleauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "googleauth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            from pageql import pageql as pql_mod
            seen = []

            async def fake_fetch(url: str, headers=None, method="GET", body=None, **kwargs):
                seen.append((url, headers, method))
                if "www.googleapis.com/oauth2/v3/userinfo" in url:
                    return {
                        "status_code": 200,
                        "headers": [],
                        "body": '{"email": "octo@example.com"}',
                    }
                return {
                    "status_code": 200,
                    "headers": [],
                    "body": 'access_token=t&token_type=bearer&scope=',
                }

            old_fetch = pql_mod.fetch
            pql_mod.fetch = fake_fetch
            monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
            monkeypatch.setenv("GOOGLE_CLIENT_ID", "123456789.apps.googleusercontent.com")
            try:
                server, task, port = await run_server_in_task(tmpdir)
                state = jws_serialize_compact('{"ongoing":1,"path":"/googleauth"}')
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/googleauth/callback?code=abc&state={state}"
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
        assert "octo@example.com" not in body
        (token_url, token_headers, token_method), (user_url, user_headers, user_method) = urls
        assert token_url.startswith("https://oauth2.googleapis.com/token")
        assert "123456789.apps.googleusercontent.com" in token_url
        assert "client_secret=secret" in token_url
        assert "code=abc" in token_url
        assert f"state={state}" in token_url
        assert user_url == "https://www.googleapis.com/oauth2/v3/userinfo"
        assert user_headers == {
            "Authorization": "Bearer t",
        }
        assert token_method == "GET"
        assert user_method == "GET"
