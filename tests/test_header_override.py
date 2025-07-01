import asyncio, tempfile
from pageql.pageqlapp import PageQLApp
from pageql.http_utils import _http_get
from playwright_helpers import run_server_in_task


def test_content_type_header_overrides(tmp_path):
    (tmp_path / "_before.pageql").write_text("{%header Content-Type 'text/html'%}")
    (tmp_path / "data.pageql").write_text("{%header Content-Type 'application/json'%}[1]")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        status, headers, body = await _http_get(f"http://127.0.0.1:{port}/data")
        server.should_exit = True
        await task
        return status, headers, body.decode()

    status, headers, body = asyncio.run(run_test())
    ct_headers = [h for h in headers if h[0] == b"content-type"]
    assert status == 200
    assert ct_headers == [(b"content-type", b"application/json")]
    assert body == "[1]"
