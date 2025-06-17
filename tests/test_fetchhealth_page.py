import asyncio
from pathlib import Path
import tempfile

from pageql.http_utils import _http_get
from playwright_helpers import run_server_in_task


def test_fetchhealth_nested_fetch(monkeypatch):
    src = Path("website/fetchhealth.pageql").read_text()
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "fetchhealth.pageql").write_text(src, encoding="utf-8")

        async def run_test():
            from pageql import pageql as pql_mod

            seen = []

            async def fake_fetch(
                url: str, headers=None, method="GET", body=None, **kwargs
            ):
                seen.append((url, kwargs.get("base_url")))
                return {
                    "status_code": 200,
                    "headers": [],
                    "body": "OK",
                }

            old_fetch = pql_mod.fetch
            pql_mod.fetch = fake_fetch
            try:
                server, task, port = await run_server_in_task(tmpdir)
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/fetchhealth"
                )
                server.should_exit = True
                await task
            finally:
                pql_mod.fetch = old_fetch
            return status, body.decode(), seen, port

        status, body, urls, port = asyncio.run(run_test())

        assert status == 200
        assert "Loading outer" in body
        assert urls == [
            ("/healthz", "http://127.0.0.1"),
            ("/healthz", "http://127.0.0.1"),
        ]
