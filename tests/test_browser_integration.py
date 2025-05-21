import sys
import pytest
from pathlib import Path
import types
import tempfile
import multiprocessing

from browser_test_utils import (
    start_server,
    start_server_with_queue,
    open_browser,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None



def test_hello_world_in_browser():
    pytest.importorskip("playwright.sync_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "hello.pageql"
        template_path.write_text("Hello world!", encoding="utf-8")

        port, proc = start_server(tmpdir)
        try:
            with open_browser() as page:
                response = page.goto(f"http://127.0.0.1:{port}/hello")
                body_text = page.evaluate("document.body.textContent")
                status = response.status if response is not None else None
        finally:
            proc.terminate()
            proc.join()

        assert status == 200
        assert "Hello world!" in body_text


def test_set_variable_in_browser():
    """Ensure directives work when rendered through the ASGI app."""
    pytest.importorskip("playwright.sync_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "greet.pageql"
        template_path.write_text("{{#set :a 'world'}}Hello {{a}}", encoding="utf-8")

        port, proc = start_server(tmpdir)
        try:
            with open_browser() as page:
                response = page.goto(f"http://127.0.0.1:{port}/greet")
                body_text = page.evaluate("document.body.textContent")
                status = response.status if response is not None else None
        finally:
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

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "react.pageql"
        template_path.write_text(
            "{{#reactive on}}{{#set a 'ww'}}hello {{a}}{{#set a 'world'}}",
            encoding="utf-8",
        )

        port, proc = start_server(tmpdir)
        try:
            with open_browser() as page:
                page.goto(f"http://127.0.0.1:{port}/react")
                page.wait_for_timeout(500)
                body_text = page.evaluate("document.body.textContent")
        finally:
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

        port, proc = start_server(tmpdir)
        try:
            with open_browser() as page:
                page.goto(f"http://127.0.0.1:{port}/count")
                page.wait_for_timeout(500)
                body_text = page.evaluate("document.body.textContent")
        finally:
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

    with tempfile.TemporaryDirectory() as tmpdir:
        template_path = Path(tmpdir) / "count_after.pageql"
        template_path.write_text(
            "{{#create table if not exists nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#set a count(*) from nums}}"
            "{{a}}",
            encoding="utf-8",
        )

        port, proc, q = start_server_with_queue(tmpdir)
        try:
            with open_browser() as page:
                page.goto(f"http://127.0.0.1:{port}/count_after")
                page.wait_for_timeout(100)
                q.put(("execute", "INSERT INTO nums(value) VALUES (1)", {}))
                q.get()
                page.goto(f"http://127.0.0.1:{port}/count_after")
                body_text = page.evaluate("document.body.textContent")
        finally:
            q.put("stop")
            proc.join()

        assert body_text == "1"
