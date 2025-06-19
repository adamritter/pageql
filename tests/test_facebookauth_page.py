import asyncio
from pathlib import Path
import tempfile

from pageql.http_utils import _http_get
from pageql import jws_serialize_compact, jws_deserialize_compact
from playwright_helpers import run_server_in_task
import json
import re


def test_facebookauth_page_renders_button(monkeypatch):
    src = Path("website/facebookauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "facebookauth.pageql").write_text(src, encoding="utf-8")
        monkeypatch.setenv("FACEBOOK_CLIENT_ID", "123456789")

        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            status, _headers, body = await _http_get(f"http://127.0.0.1:{port}/facebookauth")
            server.should_exit = True
            await task
            return status, body.decode()

        status, body = asyncio.run(run_test())

        assert status == 200
        assert "facebook.com" in body
        assert "123456789" in body
        assert "redirect_uri=http://127.0.0.1/facebookauth/callback" in body

        m = re.search(r"state=([^\"]+)", body)
        assert m is not None
        token = m.group(1)
        data = json.loads(jws_deserialize_compact(token).decode())
        assert data["ongoing"] == 1
        assert data["path"] == "/facebookauth"


def test_facebookauth_callback_fetch(monkeypatch):
    src = Path("website/facebookauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "facebookauth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            from pageql import pageql as pql_mod
            seen = []

            async def fake_fetch(url: str, headers=None, method="GET", body=None, **kwargs):
                seen.append((url, headers, method))
                if "graph.facebook.com/me" in url:
                    return {
                        "status_code": 200,
                        "headers": [],
                        "body": '{"name": "fuser"}',
                    }
                return {
                    "status_code": 200,
                    "headers": [],
                    "body": 'access_token=t&token_type=bearer&scope=',
                }

            old_fetch = pql_mod.fetch
            pql_mod.fetch = fake_fetch
            monkeypatch.setenv("FACEBOOK_CLIENT_SECRET", "secret")
            monkeypatch.setenv("FACEBOOK_CLIENT_ID", "123456789")
            try:
                server, task, port = await run_server_in_task(tmpdir)
                state = jws_serialize_compact('{"ongoing":1,"path":"/facebookauth"}')
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/facebookauth/callback?code=abc&state={state}"
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
        assert "fuser" not in body
        (token_url, token_headers, token_method), (user_url, user_headers, user_method) = urls
        assert token_url == "https://graph.facebook.com/v18.0/oauth/access_token"
        assert token_headers == {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        assert user_url == "https://graph.facebook.com/me"
        assert user_headers == {
            "Authorization": "Bearer t",
            "User-Agent": "PageQL",
        }
        assert token_method == "POST"
        assert user_method == "GET"
