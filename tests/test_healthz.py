import asyncio
import tempfile

from pageql.http_utils import _http_get
from playwright_helpers import run_server_in_task


def test_healthz_endpoint():
    with tempfile.TemporaryDirectory() as tmpdir:
        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            status, _headers, body = await _http_get(
                f"http://127.0.0.1:{port}/healthz"
            )
            server.should_exit = True
            await task
            return status, body.decode()

        status, body = asyncio.run(run_test())
        assert status == 200
        assert body == "OK"

