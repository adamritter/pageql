import asyncio
import tempfile
from pathlib import Path

from pageql.pageqlapp import PageQLApp


def test_post_without_csrf_is_rejected():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "p.pageql").write_text("ok", encoding="utf-8")
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)

            sent = []
            async def send(msg):
                sent.append(msg)
            async def receive():
                return {"type": "http.request"}
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/p",
                "headers": [],
                "query_string": b"",
            }
            cid = await app.pageql_handler(scope, receive, send)
            assert cid in app.render_contexts

            sent2 = []
            async def send2(msg):
                sent2.append(msg)
            async def receive2():
                return {"type": "http.request", "body": b"", }
            scope2 = {
                "type": "http",
                "method": "POST",
                "path": "/p",
                "headers": [(b"content-length", b"0")],
                "query_string": b"",
            }
            await app.pageql_handler(scope2, receive2, send2)
            start = next(m for m in sent2 if m["type"] == "http.response.start")
            assert start["status"] == 403
    asyncio.run(run())


def test_post_with_csrf_header_is_allowed():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "p.pageql").write_text("ok", encoding="utf-8")
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)

            sent = []
            async def send(msg):
                sent.append(msg)
            async def receive():
                return {"type": "http.request"}
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/p",
                "headers": [],
                "query_string": b"",
            }
            cid = await app.pageql_handler(scope, receive, send)

            sent2 = []
            async def send2(msg):
                sent2.append(msg)
            async def receive2():
                return {"type": "http.request", "body": b"", }
            scope2 = {
                "type": "http",
                "method": "POST",
                "path": "/p",
                "headers": [(b"ClientId", cid.encode()), (b"content-length", b"0")],
                "query_string": b"",
            }
            await app.pageql_handler(scope2, receive2, send2)
            start = next(m for m in sent2 if m["type"] == "http.response.start")
            assert start["status"] == 200
    asyncio.run(run())
