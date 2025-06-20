import asyncio
from pathlib import Path
from pageql.http_utils import _http_get
from playwright_helpers import run_server_in_task


def test_terms_and_conditions_html_served(tmp_path):
    html = Path(tmp_path) / "terms_and_conditions.html"
    html.write_text("<h1>Terms</h1>", encoding="utf-8")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        status, _headers, body_bytes = await _http_get(
            f"http://127.0.0.1:{port}/terms_and_conditions.html"
        )
        server.should_exit = True
        await task
        return status, body_bytes.decode()

    status, body = asyncio.run(run_test())
    assert status == 200
    assert "<h1>Terms</h1>" in body
