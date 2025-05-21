import http.client
import socket
import time
from pathlib import Path
from typing import Callable, Optional, Tuple
import asyncio
import pytest

from uvicorn.config import Config
from uvicorn.server import Server

from pageql.pageqlapp import PageQLApp


def get_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port



def chromium_available(playwright) -> bool:
    return Path(playwright.chromium.executable_path).exists()


async def wait_for_server_async(
    port: int,
    server: Optional[Server] = None,
    task: Optional["asyncio.Task"] = None,
    timeout: float = 5.0,
) -> None:
    start = time.time()
    while True:
        if server is not None and server.started:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.connect()
                conn.close()
                break
            except OSError:
                pass
        if time.time() - start > timeout:
            if server is not None:
                server.should_exit = True
            if task is not None:
                await task
            raise RuntimeError("Server did not start")
        await asyncio.sleep(0.05)


async def run_server_in_task(
    tmpdir: str, reload: bool = False
) -> Tuple[Server, "asyncio.Task", int]:
    port = get_free_port()
    app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=reload)
    config = Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = Server(config)
    task = asyncio.create_task(server.serve())
    try:
        await wait_for_server_async(port, server, task)
    except Exception:
        server.should_exit = True
        await task
        raise
    return server, task, port


async def _load_page_async(
    tmpdir: str,
    page: str,
    after: Optional[Callable[["async_playwright.Page", int, PageQLApp], None]] = None,
    reload: bool = False,
) -> Optional[Tuple[int, str]]:
    from playwright.async_api import async_playwright, Page

    server, task, port = await run_server_in_task(tmpdir, reload)
    app: PageQLApp = server.config.app
    async with async_playwright() as p:
        if not chromium_available(p):
            server.should_exit = True
            await task
            return None
        browser = await p.chromium.launch(args=["--no-sandbox"])
        pg: Page = await browser.new_page()
        response = await pg.goto(f"http://127.0.0.1:{port}/{page}")
        if after is not None:
            if asyncio.iscoroutinefunction(after):
                await after(pg, port, app)
            else:
                after(pg, port, app)
        await pg.wait_for_timeout(500)
        body = await pg.evaluate("document.body.textContent")
        status = response.status if response is not None else None
        await browser.close()

    server.should_exit = True
    await task
    return status, body


def load_page(tmpdir: str, page: str, after: Optional[Callable[["async_playwright.Page", int, PageQLApp], None]] = None, reload: bool = False) -> Optional[Tuple[int, str]]:
    """Utility used by integration tests to fetch a page in a browser.

    Returns ``(status_code, body_text)`` or ``None`` if Chromium is not available.
    """
    pytest.importorskip("playwright.async_api")
    return asyncio.run(_load_page_async(tmpdir, page, after, reload))
