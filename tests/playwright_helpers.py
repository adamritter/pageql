import http.client
import socket
import threading
import time
from pathlib import Path
from typing import Tuple, Optional
import asyncio

from uvicorn.config import Config
from uvicorn.server import Server

from pageql.pageqlapp import PageQLApp


def get_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_server(port: int, server: Optional[Server] = None, thread: Optional[threading.Thread] = None, timeout: float = 5.0) -> None:
    start = time.time()
    while True:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.connect()
            conn.close()
            break
        except OSError:
            if time.time() - start > timeout:
                if server is not None:
                    server.should_exit = True
                if thread is not None:
                    thread.join()
                raise RuntimeError("Server did not start")
            time.sleep(0.05)


def run_server_in_thread(tmpdir: str, reload: bool = False) -> Tuple[Server, threading.Thread, int]:
    port = get_free_port()
    container: dict[str, Server] = {}

    def run() -> None:
        app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=reload)
        config = Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = Server(config)
        container["server"] = server
        server.run()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    while "server" not in container:
        time.sleep(0.01)

    wait_for_server(port, container["server"], thread)
    return container["server"], thread, port


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
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.connect()
            conn.close()
            break
        except OSError:
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
