import asyncio
from pathlib import Path
import tempfile

from pageql.http_utils import _http_get
from playwright_helpers import run_server_in_task


def test_githubauth_page_renders_button():
    src = Path("website/githubauth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "githubauth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            status, _headers, body = await _http_get(f"http://127.0.0.1:{port}/githubauth")
            server.should_exit = True
            await task
            return status, body.decode()

        status, body = asyncio.run(run_test())

        assert status == 200
        assert "github.com/login/oauth/authorize" in body
        assert "Iv23liGYF2X5uR4izdC3" in body

