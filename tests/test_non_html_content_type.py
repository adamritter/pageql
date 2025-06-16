import asyncio
import tempfile
from pathlib import Path
from pageql.pageqlapp import PageQLApp


def test_non_html_content_type_omits_wrappers():
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "data.pageql").write_text("{{#header Content-Type 'application/json'}}{\"foo\": 1}", encoding="utf-8")
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
            sent = []

            async def send(msg):
                sent.append(msg)

            async def receive():
                return {"type": "http.request"}

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/data",
                "headers": [],
                "query_string": b"",
            }
            await app.pageql_handler(scope, receive, send)

            start = next(m for m in sent if m["type"] == "http.response.start")
            headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
            body = next(m for m in sent if m["type"] == "http.response.body")["body"].decode()
            return headers, body

    headers, body = asyncio.run(run())
    assert headers.get("content-type") == "application/json"
    assert body == '{"foo": 1}'
    assert "<html" not in body.lower()
    assert "<body" not in body.lower()
