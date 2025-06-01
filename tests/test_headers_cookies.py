import asyncio
import tempfile
from pathlib import Path

from pageql.pageqlapp import PageQLApp
from pageql.pageql import PageQL


def test_header_cookie_in_render_result():
    r = PageQL(":memory:")
    r.load_module("mod", "{{#header X-Test 'v'}}{{#cookie sess 'val' path='/'}}ok")
    res = r.render("/mod")
    assert ("X-Test", "v") in res.headers
    assert ("sess", "val", {"path": "/"}) in res.cookies


def test_header_cookie_sent():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "h.pageql").write_text(
                "{{#header X-Mode 'on'}}{{#cookie cid 'c123' path='/' httponly}}hi",
                encoding="utf-8",
            )
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
            sent = []

            async def send(msg):
                sent.append(msg)

            async def receive():
                return {"type": "http.request"}

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/h",
                "headers": [],
                "query_string": b"",
            }
            await app.pageql_handler(scope, receive, send)
            start = next(m for m in sent if m["type"] == "http.response.start")
            headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
            assert headers["x-mode"] == "on"
            cookie = [v.decode() for k, v in start["headers"] if k == b"Set-Cookie"][0]
            assert cookie.startswith("cid=c123")
            assert "httponly" in cookie.lower()

    asyncio.run(run())


def test_cookie_map_available():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "c.pageql").write_text("{{ cookies.session }}", encoding="utf-8")
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
            sent: list[dict] = []

            async def send(msg):
                sent.append(msg)

            async def receive():
                return {"type": "http.request"}

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/c",
                "headers": [(b"cookie", b"session=s123")],
                "query_string": b"",
            }

            await app.pageql_handler(scope, receive, send)
            body = next(m for m in sent if m["type"] == "http.response.body")["body"].decode()
            assert "s123" in body

    asyncio.run(run())
