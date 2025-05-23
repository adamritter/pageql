import sys
from pathlib import Path
import types
import tempfile
import http.client
import asyncio
import pytest
# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from playwright_helpers import run_server_in_task


def test_app_returns_404_for_missing_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)

            def make_request():
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("GET", "/missing")
                resp = conn.getresponse()
                status = resp.status
                resp.read()
                conn.close()
                return status

            status_inner = await asyncio.to_thread(make_request)

            server.should_exit = True
            await task
            return status_inner

        status = asyncio.run(run_test())

        assert status == 404

