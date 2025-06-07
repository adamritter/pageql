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

