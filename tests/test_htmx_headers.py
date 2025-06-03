import asyncio
import tempfile
from pathlib import Path
import pytest

from pageql.pageqlapp import PageQLApp
from pageql.client_script import client_script

def test_htmx_none_mode_omits_js_headers():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "hello.pageql").write_text("hello", encoding="utf-8")
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)

            sent = []
            async def send(msg):
                sent.append(msg)
            async def receive():
                return {"type": "http.request"}

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/hello",
                "headers": [(b"hx-mode", b"none")],
                "query_string": b"",
            }
            await app.pageql_handler(scope, receive, send)

            body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
            assert "hello" in body
            assert "/htmx.min.js" not in body
            assert "reload-request-ws" not in body

    asyncio.run(run())
