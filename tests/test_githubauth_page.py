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


def test_githubauth_callback_fetch():
    src = Path("website/githubauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "githubauth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            from pageql import pageql as pql_mod
            seen = {}

            def fake_fetch(url: str):
                seen["url"] = url
                return {"status_code": 200, "headers": [], "body": "resp"}

            old_fetch = pql_mod.fetch_sync
            pql_mod.fetch_sync = fake_fetch
            try:
                server, task, port = await run_server_in_task(tmpdir)
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/githubauth/callback?code=abc&state=xyz"
                )
                server.should_exit = True
                await task
            finally:
                pql_mod.fetch_sync = old_fetch
            return status, body.decode(), seen.get("url")

        status, body, url = asyncio.run(run_test())

        assert status == 200
        assert "resp" in body
        assert url.startswith("https://github.com/login/oauth/access_token")
        assert "Iv23liGYF2X5uR4izdC3" in url
        assert "code=abc" in url
        assert "state=xyz" in url

