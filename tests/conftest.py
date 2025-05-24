import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

import asyncio
import pytest
from playwright_helpers import chromium_available


@pytest.fixture(scope="module")
def browser():
    """Launch a single Playwright browser instance for integration tests."""
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    p = loop.run_until_complete(async_playwright().start())
    if not chromium_available(p):
        loop.run_until_complete(p.stop())
        loop.close()
        pytest.skip("Chromium not available for Playwright")
    browser = loop.run_until_complete(p.chromium.launch(args=["--no-sandbox"]))
    yield loop, p, browser
    loop.run_until_complete(browser.close())
    loop.run_until_complete(p.stop())
    loop.close()
