import sys
import importlib.util
import tempfile
import types
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageqlapp import PageQLApp
from playwright_helpers import load_page




def test_hello_world_in_browser():
    pytest.importorskip("playwright.async_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "hello.pageql").write_text("Hello world!", encoding="utf-8")

        result = load_page(tmpdir, "hello")
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        status, body_text = result

        assert status == 200
        assert "Hello world!" in body_text


def test_set_variable_in_browser():
    """Ensure directives work when rendered through the ASGI app."""
    pytest.importorskip("playwright.async_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "greet.pageql").write_text("{{#set :a 'world'}}Hello {{a}}", encoding="utf-8")

        result = load_page(tmpdir, "greet")
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        status, body_text = result

        assert status == 200
        assert "Hello world" in body_text


def test_reactive_set_variable_in_browser():
    """Ensure reactive mode updates are sent to the browser."""
    pytest.importorskip("playwright.async_api")
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "react.pageql").write_text(
            "{{#reactive on}}{{#set a 'ww'}}hello {{a}}{{#set a 'world'}}",
            encoding="utf-8",
        )

        body_text = load_page(tmpdir, "react")
        if body_text is None:
            pytest.skip("Chromium not available for Playwright")
        _, text = body_text

        assert text == "hello world"


def test_reactive_count_insert_in_browser():
    """Count updates should be delivered to the browser when rows are inserted."""
    pytest.importorskip("playwright.async_api")
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count.pageql").write_text(
            "{{#create table nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#set a count(*) from nums}}"
            "{{a}}"
            "{{#insert into nums(value) values (1)}}",
            encoding="utf-8",
        )

        result = load_page(tmpdir, "count")
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        _, body_text = result

        assert body_text == "1"


def test_reactive_count_insert_via_execute():
    """Count updates should propagate when inserting after initial load."""
    pytest.importorskip("playwright.async_api")
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count_after.pageql").write_text(
            "{{#create table if not exists nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#set a count(*) from nums}}"
            "{{a}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            await page.wait_for_timeout(500)
            app.pageql_engine.tables.executeone(
                "INSERT INTO nums(value) VALUES (1)", {}
            )

        result = load_page(tmpdir, "count_after", after, reload=True)
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        _, body_text = result

        assert body_text == "1"
