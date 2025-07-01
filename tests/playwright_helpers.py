import asyncio
import re
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
    app = PageQLApp(
        ":memory:",
        tmpdir,
        create_db=True,
        should_reload=reload,
        csrf_protect=False,
    )
    config = Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    assert server.servers and server.servers[0].sockets
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port

def strip_not_none(text: Optional[str]) -> str:
    if text is None:
        return None
    return text.strip()

async def _load_page_async(
    port: int,
    page: str,
    app: PageQLApp,
    after: Optional[Callable[["async_playwright.Page", int, PageQLApp], None]] = None,
    browser=None,
) -> Optional[Tuple[int, str]]:

    pg = await browser.new_page()
    response = await pg.goto(f"http://127.0.0.1:{port}/{page}")

    client_id = None
    if response is not None:
        try:
            html = await response.text()
            m = re.search(r"clientId\s*=\s*\"([^\"]+)\"", html)
            if m:
                client_id = m.group(1)
        except Exception:
            pass

    if after is not None:
        if asyncio.iscoroutinefunction(after):
            await after(pg, port, app)
        else:
            after(pg, port, app)

    body: Optional[str]
    if client_id:
        # ``after`` may navigate again, creating a new WebSocket with a new id
        ids = [client_id]
        ids.extend(cid for cid in app.websockets.keys() if cid != client_id)
        body = None
        for cid in ids:
            body = await app.get_text_body(cid)
            if body is not None:
                body = body.strip()
                break
    else:
        body = None

    status = response.status if response is not None else None
    body = strip_not_none(await app.get_text_body(client_id))

    return status, body, client_id
