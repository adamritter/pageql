import sys
import pytest
from pathlib import Path
import types
import tempfile
import socket
import time
import http.client
from multiprocessing import Process
from uvicorn.config import Config
from uvicorn.server import Server
import threading
import multiprocessing

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageqlapp import PageQLApp


def _get_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(port, tmpdir, reload=False):
    app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=reload)
    config = Config(app, host="127.0.0.1", port=port, log_level="warning")
    Server(config).run()


def _serve_with_queue(port, tmpdir, q):
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


def test_hello_world_in_browser():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "hello.pageql"
        template_path.write_text("Hello world!", encoding="utf-8")

        port = _get_free_port()
        proc = Process(target=_serve, args=(port, tmpdir))
        proc.start()

        start = time.time()
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.connect()
                conn.close()
                break
            except OSError:
                if time.time() - start > 5:
                    proc.terminate()
                    proc.join()
                    raise RuntimeError("Server did not start")
                time.sleep(0.05)

        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
            if not Path(chromium_path).exists():
                proc.terminate()
                proc.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            response = page.goto(f"http://127.0.0.1:{port}/hello")
            body_text = page.evaluate("document.body.textContent")
            status = response.status if response is not None else None
            browser.close()

        proc.terminate()
        proc.join()

        assert status == 200
        assert "Hello world!" in body_text


def test_set_variable_in_browser():
    """Ensure directives work when rendered through the ASGI app."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "greet.pageql"
        template_path.write_text("{{#set :a 'world'}}Hello {{a}}", encoding="utf-8")

        port = _get_free_port()
        proc = Process(target=_serve, args=(port, tmpdir))
        proc.start()

        start = time.time()
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.connect()
                conn.close()
                break
            except OSError:
                if time.time() - start > 5:
                    proc.terminate()
                    proc.join()
                    raise RuntimeError("Server did not start")
                time.sleep(0.05)

        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
            if not Path(chromium_path).exists():
                proc.terminate()
                proc.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            response = page.goto(f"http://127.0.0.1:{port}/greet")
            body_text = page.evaluate("document.body.textContent")
            status = response.status if response is not None else None
            browser.close()

        proc.terminate()
        proc.join()

        assert status == 200
        assert "Hello world" in body_text


def test_reactive_set_variable_in_browser():
    """Ensure reactive mode updates are sent to the browser."""
    pytest.importorskip("playwright.sync_api")
    import importlib.util
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "react.pageql"
        template_path.write_text(
            "{{#reactive on}}{{#set a 'ww'}}hello {{a}}{{#set a 'world'}}",
            encoding="utf-8",
        )

        port = _get_free_port()
        proc = Process(target=_serve, args=(port, tmpdir))
        proc.start()

        start = time.time()
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.connect()
                conn.close()
                break
            except OSError:
                if time.time() - start > 5:
                    proc.terminate()
                    proc.join()
                    raise RuntimeError("Server did not start")
                time.sleep(0.05)

        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
            if not Path(chromium_path).exists():
                proc.terminate()
                proc.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/react")
            page.wait_for_timeout(500)
            body_text = page.evaluate("document.body.textContent")
            browser.close()

        proc.terminate()
        proc.join()

        assert body_text == "hello world"


def test_reactive_count_insert_in_browser():
    """Count updates should be delivered to the browser when rows are inserted."""
    pytest.importorskip("playwright.sync_api")
    import importlib.util
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "count.pageql"
        template_path.write_text(
            "{{#create table nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#set a count(*) from nums}}"
            "{{a}}"
            "{{#insert into nums(value) values (1)}}",
            encoding="utf-8",
        )

        port = _get_free_port()
        proc = Process(target=_serve, args=(port, tmpdir))
        proc.start()

        start = time.time()
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.connect()
                conn.close()
                break
            except OSError:
                if time.time() - start > 5:
                    proc.terminate()
                    proc.join()
                    raise RuntimeError("Server did not start")
                time.sleep(0.05)

        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
            if not Path(chromium_path).exists():
                proc.terminate()
                proc.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/count")
            page.wait_for_timeout(500)
            body_text = page.evaluate("document.body.textContent")
            browser.close()

        proc.terminate()
        proc.join()

        assert body_text == "1"


def test_reactive_count_insert_via_execute():
    """Count updates should propagate when inserting after initial load."""
    pytest.importorskip("playwright.sync_api")
    import importlib.util
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "count_after.pageql"
        template_path.write_text(
            "{{#create table nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#set a count(*) from nums}}"
            "{{a}}",
            encoding="utf-8",
        )

        port = _get_free_port()
        q = multiprocessing.Queue()
        proc = Process(target=_serve_with_queue, args=(port, tmpdir, q))
        proc.start()

        start = time.time()
        while True:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.connect()
                conn.close()
                break
            except OSError:
                if time.time() - start > 5:
                    q.put("stop")
                    proc.join()
                    raise RuntimeError("Server did not start")
                time.sleep(0.05)

        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
            if not Path(chromium_path).exists():
                q.put("stop")
                proc.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/count_after")
            page.wait_for_timeout(100)
            q.put(("execute", "INSERT INTO nums(value) VALUES (1)", {}))
            q.get()
            page.wait_for_timeout(500)
            body_text = page.evaluate("document.body.textContent")
            browser.close()

        q.put("stop")
        proc.join()

        assert body_text == "1"
