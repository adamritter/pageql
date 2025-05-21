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

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/greet")
        resp = conn.getresponse()
        body = resp.read().decode()
        status = resp.status
        conn.close()

        proc.terminate()
        proc.join()

        assert status == 200
        assert "Hello world" in body


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
