import asyncio
from pathlib import Path

from pageql.http_utils import _http_get
from playwright_helpers import run_server_in_task


def test_directory_index_pageql_served(tmp_path):
    d = Path(tmp_path) / "foo"
    d.mkdir()
    (d / "index.pageql").write_text("hello", encoding="utf-8")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        status, _headers, body_bytes = await _http_get(
            f"http://127.0.0.1:{port}/foo"
        )
        server.should_exit = True
        await task
        return status, body_bytes.decode()

    status, body = asyncio.run(run_test())
    assert status == 200
    assert "hello" in body


def test_directory_index_html_served(tmp_path):
    d = Path(tmp_path) / "bar"
    d.mkdir()
    (d / "index.html").write_text("<h1>Bar</h1>", encoding="utf-8")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        status, _headers, body_bytes = await _http_get(
            f"http://127.0.0.1:{port}/bar"
        )
        server.should_exit = True
        await task
        return status, body_bytes.decode()

    status, body = asyncio.run(run_test())
    assert status == 200
    assert "<h1>Bar</h1>" in body
