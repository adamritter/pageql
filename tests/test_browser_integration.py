import sys
import pytest
import asyncio
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


def _serve(port, tmpdir):
    app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
    config = Config(app, host="127.0.0.1", port=port, log_level="warning")
    Server(config).run()


def test_hello_world_in_browser():
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

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/hello")
        resp = conn.getresponse()
        body = resp.read().decode()
        status = resp.status
        conn.close()

        proc.terminate()
        proc.join()

        assert status == 200
        assert "Hello world!" in body


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
    pyppeteer = pytest.importorskip("pyppeteer")
    from pyppeteer import chromium_downloader, launch

    chromium = chromium_downloader.chromium_executable()
    if not Path(chromium).exists():
        pytest.skip("Chromium not available for pyppeteer")

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

        async def _run():
            browser = await launch(
                executablePath=chromium,
                args=["--no-sandbox"],
                handleSIGINT=False,
                handleSIGTERM=False,
                handleSIGHUP=False,
            )
            page = await browser.newPage()
            await page.goto(f"http://127.0.0.1:{port}/react")
            body = await page.evaluate("document.body.textContent")
            await browser.close()
            return body

        body_text = asyncio.get_event_loop().run_until_complete(_run())

        proc.terminate()
        proc.join()

        assert body_text == "hello world"
