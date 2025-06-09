import sys
from pathlib import Path
import types
import pytest

pytestmark = pytest.mark.anyio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Provide a stub for watchfiles.awatch used by PageQLApp if imported
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *a, **k: None

from pageql.pageql_async import PageQLAsync


async def test_render_async_returns_expected_result():
    r = PageQLAsync(":memory:")
    r.load_module("hello", "hi")
    res = await r.render_async("/hello", reactive=False)
    assert res.body == "hi"


async def test_fetch_async_queues_task(monkeypatch):
    calls = []

    async def fake_fetch(url: str):
        calls.append(url)
        return {"status_code": 200, "headers": [], "body": "ok"}

    import pageql.pageql_async as pqa
    monkeypatch.setattr(pqa, "fetch", fake_fetch)
    from pageql import pageql as pql_mod

    r = PageQLAsync(":memory:")
    r.load_module("m", "{{#fetch async d from 'http://x'}}{{d__body}}")
    res = await r.render_async("/m", reactive=False)
    assert res.body.strip() == "None"
    assert len(pql_mod.tasks) == 1
    await pql_mod.tasks.pop()  # run the queued task
    assert calls == ["http://x"]
    pql_mod.tasks.clear()

