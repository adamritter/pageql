import asyncio
import tempfile
from pathlib import Path

from pageql.pageqlapp import PageQLApp


def test_basic_auth_sessionless_invalid_cookie_returns_500():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "basic_auth_sessionless.pageql").write_text(
                Path("website/basic_auth_sessionless.pageql").read_text(),
                encoding="utf-8",
            )
            app = PageQLApp(
                ":memory:", tmpdir, create_db=True, should_reload=False, csrf_protect=False
            )

            sent = []

            async def send(msg):
                sent.append(msg)

            async def receive():
                return {"type": "http.request"}

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/basic_auth_sessionless",
                "headers": [(b"cookie", b"session=invalid")],
                "query_string": b"",
            }

            await app.pageql_handler(scope, receive, send)
            start = next(m for m in sent if m["type"] == "http.response.start")
            assert start["status"] == 500

    asyncio.run(run())
