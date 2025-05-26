import sys
import importlib.util
import tempfile
import types
from pathlib import Path
import warnings
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

pytestmark = [
    pytest.mark.filterwarnings(
        "ignore:websockets.server.WebSocketServerProtocol is deprecated",
        category=DeprecationWarning,
    ),
    pytest.mark.filterwarnings(
        "ignore:remove second argument of ws_handler", category=DeprecationWarning
    ),
    pytest.mark.filterwarnings(
        "ignore:This process .* fork\\(\\) may lead to deadlocks in the child.",
        category=DeprecationWarning,
    ),
]

from pageql.pageqlapp import PageQLApp
from playwright_helpers import load_page




def test_hello_world_in_browser():
    pytest.importorskip("playwright.async_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "hello.pageql").write_text("Hello world!", encoding="utf-8")

        result = load_page(tmpdir, "hello")
        status, body_text = result

        assert status == 200
        assert "Hello world!" in body_text


def test_set_variable_in_browser():
    """Ensure directives work when rendered through the ASGI app."""
    pytest.importorskip("playwright.async_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "greet.pageql").write_text("{{#set :a 'world'}}Hello {{a}}", encoding="utf-8")

        result = load_page(tmpdir, "greet")
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
            "{{#create table vars(val TEXT)}}"
            "{{#insert into vars(val) values ('ww')}}"
            "{{#reactive on}}"
            "{{#set a (select val from vars)}}"
            "hello {{a}}"
            "{{#update vars set val = 'world'}}",
            encoding="utf-8",
        )

        body_text = load_page(tmpdir, "react")
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
        _, body_text = result

        assert body_text == "1"


def test_reactive_count_delete_via_execute():
    """Count should decrement when a row is deleted via executeone."""
    pytest.importorskip("playwright.async_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count_after_delete.pageql").write_text(
            "{{#create table if not exists nums(value INTEGER)}}"
            "{{#insert into nums(value) values (1)}}"
            "{{#reactive on}}"
            "{{#set a count(*) from nums}}"
            "{{a}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            await page.wait_for_timeout(500)
            app.pageql_engine.tables.executeone(
                "DELETE FROM nums WHERE value = 1",
                {},
            )

        result = load_page(tmpdir, "count_after_delete", after, reload=True)
        _, body_text = result

        assert body_text == "0"

def test_insert_via_execute_after_click():
    """Inserting via ``executeone`` should display the added text reactively."""
    pytest.importorskip("playwright.async_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "msgs.pageql").write_text(
            "{{#create table if not exists msgs(text TEXT)}}"
            "{{#reactive on}}"
            "{{#from msgs}}{{text}}{{/from}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            await page.wait_for_timeout(500)
            app.pageql_engine.tables.executeone(
                "INSERT INTO msgs(text) VALUES (:text)", {"text": "hello"}
            )
            await page.wait_for_timeout(500)

        result = load_page(tmpdir, "msgs", after, reload=True)
        _, body_text = result

        assert "hello" in body_text


def test_todos_add_partial_in_separate_page():
    """Render todos then invoke the add partial from a second page."""
    pytest.importorskip("playwright.async_api")

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(__file__).resolve().parent.parent / "website" / "todos.pageql"
        Path(tmpdir, "todos.pageql").write_text(src.read_text(), encoding="utf-8")

        async def after(page, port, app: PageQLApp):
            await page.wait_for_timeout(500)
            page2 = await page.context.browser.new_page()
            await page2.request.post(
                f"http://127.0.0.1:{port}/todos/add",
                data="text=hello",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            await page2.close()
            await page.goto(f"http://127.0.0.1:{port}/todos")
            await page.wait_for_timeout(500)

        result = load_page(tmpdir, "todos", after, reload=True)
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        status, body_text = result

        assert status == 200
        assert "hello" in body_text
