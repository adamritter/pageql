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
            assert "/htmx.js" not in body
            assert "reload-request-ws" not in body

    asyncio.run(run())


def test_htmx_request_omits_js_headers():
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
                "headers": [(b"hx-request", b"true")],
                "query_string": b"",
            }
            await app.pageql_handler(scope, receive, send)

            body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
            assert "hello" in body
            assert "/htmx.js" not in body
            assert "reload-request-ws" not in body

    asyncio.run(run())


def test_static_html_flag_disables_client_script():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)

            sent = []

            async def send(msg):
                sent.append(msg)

            async def receive():
                return {"type": "http.request"}

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/index.html",
                "headers": [],
                "query_string": b"",
            }

            await app.pageql_handler(scope, receive, send)

            body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
            assert "/htmx.js" in body

            sent.clear()
            app.static_html = True
            await app.pageql_handler(scope, receive, send)

            body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
            assert "/htmx.js" not in body
            assert "reload-request-ws" not in body

    asyncio.run(run())
