import sys
import pytest
from pathlib import Path
import types
import tempfile
import http.client
import time
from uvicorn.config import Config
from uvicorn.server import Server
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageqlapp import PageQLApp
from playwright_helpers import chromium_available, get_free_port, run_server_in_thread




def test_hello_world_in_browser():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "hello.pageql"
        template_path.write_text("Hello world!", encoding="utf-8")

        server, thread, port = run_server_in_thread(tmpdir)

        with sync_playwright() as p:
            if not chromium_available(p):
                server.should_exit = True
                thread.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            response = page.goto(f"http://127.0.0.1:{port}/hello")
            body_text = page.evaluate("document.body.textContent")
            status = response.status if response is not None else None
            browser.close()

        server.should_exit = True
        thread.join()

        assert status == 200
        assert "Hello world!" in body_text


def test_set_variable_in_browser():
    """Ensure directives work when rendered through the ASGI app."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "greet.pageql"
        template_path.write_text("{{#set :a 'world'}}Hello {{a}}", encoding="utf-8")

        server, thread, port = run_server_in_thread(tmpdir)

        with sync_playwright() as p:
            if not chromium_available(p):
                server.should_exit = True
                thread.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            response = page.goto(f"http://127.0.0.1:{port}/greet")
            body_text = page.evaluate("document.body.textContent")
            status = response.status if response is not None else None
            browser.close()

        server.should_exit = True
        thread.join()

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

        server, thread, port = run_server_in_thread(tmpdir)

        with sync_playwright() as p:
            if not chromium_available(p):
                server.should_exit = True
                thread.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/react")
            page.wait_for_timeout(500)
            body_text = page.evaluate("document.body.textContent")
            browser.close()

        server.should_exit = True
        thread.join()

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

        server, thread, port = run_server_in_thread(tmpdir)

        with sync_playwright() as p:
            if not chromium_available(p):
                server.should_exit = True
                thread.join()
                pytest.skip("Chromium not available for Playwright")
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/count")
            page.wait_for_timeout(500)
            body_text = page.evaluate("document.body.textContent")
            browser.close()

        server.should_exit = True
        thread.join()

        assert body_text == "1"


def test_reactive_count_insert_via_execute():
    """Count updates should propagate when inserting after initial load."""
    pytest.importorskip("playwright.async_api")
    import importlib.util
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")
    from playwright.async_api import async_playwright

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "count_after.pageql"
        template_path.write_text(
            "{{#create table if not exists nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#set a count(*) from nums}}"
            "{{a}}",
            encoding="utf-8",
        )

        port = get_free_port()
        app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
        config = Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = Server(config)

        async def run_test():
            server_task = asyncio.create_task(server.serve())
            start = time.time()
            while True:
                try:
                    conn = http.client.HTTPConnection("127.0.0.1", port)
                    conn.connect()
                    conn.close()
                    break
                except OSError:
                    if time.time() - start > 5:
                        server.should_exit = True
                        await server_task
                        raise RuntimeError("Server did not start")
                    await asyncio.sleep(0.05)

            async with async_playwright() as p:
                if not chromium_available(p):
                    server.should_exit = True
                    await server_task
                    return None
                browser = await p.chromium.launch(args=["--no-sandbox"])
                page = await browser.new_page()
                await page.goto(f"http://127.0.0.1:{port}/count_after")
                await page.wait_for_timeout(500)
                body_text_inner = await page.evaluate("document.body.textContent")
                app.pageql_engine.tables.executeone(
                    "INSERT INTO nums(value) VALUES (1)", {}
                )
                await page.reload()
                await page.wait_for_timeout(500)
                body_text_inner = await page.evaluate("document.body.textContent")
                await browser.close()

            server.should_exit = True
            await server_task
            return body_text_inner

        body_text = asyncio.run(run_test())
        if body_text is None:
            pytest.skip("Chromium not available for Playwright")

        assert body_text == "1"
