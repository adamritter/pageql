import sys
import tempfile
import asyncio
from pathlib import Path
import pytest

pytestmark = pytest.mark.anyio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))




from pageql.pageqlapp import PageQLApp
from playwright_helpers import _load_page_async, run_server_in_task

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright


@pytest.fixture(scope="module")
async def setup():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)

    yield browser

    await browser.close()
    await playwright.stop()


async def start_server(tmpdir: str, reload: bool = False):
    server, task, port = await run_server_in_task(tmpdir, reload)
    app: PageQLApp = server.config.app
    return server, task, port, app


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
@pytest.mark.timeout(6)
async def test_infinite_scroll_in_browser(setup):
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(__file__).resolve().parent.parent / "website" / "infinite_scroll.pageql"
        Path(tmpdir, "infinite_scroll.pageql").write_text(src.read_text(), encoding="utf-8")

        server, task, port, app = await start_server(tmpdir)

        async def after(page, port, app: PageQLApp):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

        result = await _load_page_async(
            port,
            "infinite_scroll",
            app,
            after,
            browser=setup,
        )
        status, body_text, client_id = result

        assert status == 200
        assert "/infinite_scroll/numbers/" in body_text
        assert body_text.count("<br>") >= 1

        server.should_exit = True
        await task

