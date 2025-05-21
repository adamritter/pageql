import socket
import time
import http.client
from multiprocessing import Process
import multiprocessing
import threading
from pathlib import Path
from contextlib import contextmanager
import pytest

from uvicorn.config import Config
from uvicorn.server import Server

from pageql.pageqlapp import PageQLApp
import sqlite3


def get_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve_app(port, tmpdir, reload=False):
    original_connect = sqlite3.connect
    sqlite3.connect = lambda db, *a, **kw: original_connect(db, *a, check_same_thread=False, **kw)
    try:
        app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=reload)
        config = Config(app, host="127.0.0.1", port=port, log_level="warning")
        Server(config).run()
    finally:
        sqlite3.connect = original_connect


def serve_app_with_queue(port, tmpdir, q):
    original_connect = sqlite3.connect
    sqlite3.connect = lambda db, *a, **kw: original_connect(db, *a, check_same_thread=False, **kw)
    try:
        app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
        config = Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = Server(config)
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        while True:
            cmd = q.get()
            if cmd == "stop":
                server.should_exit = True
                t.join()
                break
            elif isinstance(cmd, tuple) and cmd[0] == "execute":
                sql, params = cmd[1], cmd[2]
                app.pageql_engine.tables.executeone(sql, params)
                q.put("done")
    finally:
        sqlite3.connect = original_connect


def wait_for_server(port, timeout=5):
    start = time.time()
    while True:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.connect()
            conn.close()
            return
        except OSError:
            if time.time() - start > timeout:
                raise RuntimeError("Server did not start")
            time.sleep(0.05)


def start_server(tmpdir, reload=False):
    port = get_free_port()
    proc = Process(target=serve_app, args=(port, tmpdir, reload))
    proc.start()
    wait_for_server(port)
    return port, proc


def start_server_with_queue(tmpdir):
    port = get_free_port()
    q = multiprocessing.Queue()
    proc = Process(target=serve_app_with_queue, args=(port, tmpdir, q))
    proc.start()
    wait_for_server(port)
    return port, proc, q


@contextmanager
def open_browser():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        chromium_path = p.chromium.executable_path
        if not Path(chromium_path).exists():
            pytest.skip("Chromium not available for Playwright")
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        try:
            yield page
        finally:
            browser.close()
