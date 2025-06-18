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
        assert "None" in body
        assert urls == [
            ("/healthz", "http://127.0.0.1"),
            ("/healthz", "http://127.0.0.1"),
        ]


def test_fetchhealth_nested_fetch_scripts(monkeypatch):
    src = Path("website/fetchhealth.pageql").read_text()
    src = src.replace("/healthz", "http://x/healthz")

    async def run_test():
        from pageql import pageql as pql_mod

        async def fake_fetch(url: str, headers=None, method="GET", body=None, **kwargs):
            return {"status_code": 200, "headers": [], "body": "OK"}

        old_fetch = pql_mod.fetch
        pql_mod.fetch = fake_fetch
        try:
            r = pql_mod.PageQL(":memory:")
            r.load_module("fetchhealth", src)
            result = r.render("/fetchhealth")
            ctx = result.context
            while pql_mod.tasks:
                await pql_mod.tasks.pop(0)
                await asyncio.sleep(0)
            await asyncio.sleep(0.1)
            scripts = ctx.scripts
        finally:
            pql_mod.fetch = old_fetch
            pql_mod.tasks.clear()
        return scripts

    scripts = asyncio.run(run_test())

    assert scripts[0] == 'pset(1,"OK")'
    assert scripts[2] == 'pset(3,"OK")'
    assert scripts[3] == 'pset(2,"Fetched twice")'
    assert scripts[1].startswith('pset(0,"<script>pstart(2)</script>')
    assert '<script>pstart(3)</script>' in scripts[1]
    assert scripts[1].endswith('<script>pend(2)</script>")')
