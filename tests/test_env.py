import asyncio, tempfile
from pathlib import Path
from pageql.pageqlapp import PageQLApp


def test_environment_map_available(monkeypatch):
    async def run():
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "e.pageql").write_text("{{ env.MY_VAR }}", encoding="utf-8")
            app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
            sent: list[dict] = []

            async def send(msg):
                sent.append(msg)

            async def receive():
                return {"type": "http.request"}

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/e",
                "headers": [],
                "query_string": b"",
            }

            monkeypatch.setenv("MY_VAR", "hello")
            await app.pageql_handler(scope, receive, send)
            body = next(m for m in sent if m["type"] == "http.response.body")["body"].decode()
            assert "hello" in body

    asyncio.run(run())
