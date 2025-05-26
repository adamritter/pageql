import asyncio
from pathlib import Path
from typing import Callable, Optional, Tuple

import pytest

from uvicorn.config import Config
from uvicorn.server import Server

from pageql.pageqlapp import PageQLApp


def chromium_available(playwright) -> bool:
    return Path(playwright.chromium.executable_path).exists()

async def run_server_in_task(
    tmpdir: str, reload: bool = False
) -> Tuple[Server, "asyncio.Task", int]:
    app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=reload)
    config = Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    assert server.servers and server.servers[0].sockets
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


async def _load_page_async(
    tmpdir: str,
    page: str,
    after: Optional[Callable[["async_playwright.Page", int, PageQLApp], None]] = None,
    reload: bool = False,
    browser = None,
) -> Optional[Tuple[int, str]]:
    from playwright.async_api import async_playwright, Page

    server, task, port = await run_server_in_task(tmpdir, reload)
    app: PageQLApp = server.config.app
    async with async_playwright() as p:
        if not chromium_available(p):
            server.should_exit = True
            await task
            return None
        has_browser = browser is not None
        if browser is None:
            browser = await p.chromium.launch(args=["--no-sandbox"])
        pg: Page = await browser.new_page()
        response = await pg.goto(f"http://127.0.0.1:{port}/{page}")
        if after is not None:
            if asyncio.iscoroutinefunction(after):
                await after(pg, port, app)
            else:
                after(pg, port, app)
        await pg.wait_for_timeout(500)
        body = (await pg.evaluate("document.body.textContent")).strip()
        status = response.status if response is not None else None
        if not has_browser:
            await browser.close()

    server.should_exit = True
    await task
    return status, body


def load_page(tmpdir: str, page: str, after: Optional[Callable[["async_playwright.Page", int, PageQLApp], None]] = None, reload: bool = False, browser = None) -> Optional[Tuple[int, str]]:
    """Utility used by integration tests to fetch a page in a browser.

    Returns ``(status_code, body_text)`` or ``None`` if Chromium is not available.
    """
    pytest.importorskip("playwright.async_api")
    return asyncio.run(_load_page_async(tmpdir, page, after, reload, browser))
