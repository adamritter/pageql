import sys
import importlib.util
import tempfile
import types
from pathlib import Path
import pytest

pytestmark = pytest.mark.anyio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))

async def _awatch_stub(*args, **kwargs):
    if False:
        yield None

sys.modules["watchfiles"].awatch = _awatch_stub

from pageql.pageqlapp import PageQLApp
from playwright_helpers import _load_page_async

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright

@pytest.fixture(scope="module")
async def browser():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    print("launched")

    yield browser  # ← your tests can now use this browser

    await browser.close()
    await playwright.stop()

@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_hello_world_in_browser(browser):

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "hello.pageql").write_text("Hello world!", encoding="utf-8")

        result = await _load_page_async(tmpdir, "hello", browser=browser)
        status, body_text = result

        assert status == 200
        assert "Hello world!" in body_text


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_set_variable_in_browser(browser):
    """Ensure directives work when rendered through the ASGI app."""

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "greet.pageql").write_text("{{#let :a = 'world'}}Hello {{a}}", encoding="utf-8")

        result = await _load_page_async(tmpdir, "greet", browser=browser)
        status, body_text = result

        assert status == 200
        assert "Hello world" in body_text


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_set_variable_in_browser(browser):
    """Ensure reactive mode updates are sent to the browser."""
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
            "{{#let a = (select val from vars)}}"
            "hello {{a}}"
            "{{#update vars set val = 'world'}}",
            encoding="utf-8",
        )

        body_text = await _load_page_async(tmpdir, "react", browser=browser)
        _, text = body_text

        assert text == "hello world"


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_count_insert_in_browser(browser):
    """Count updates should be delivered to the browser when rows are inserted."""
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count.pageql").write_text(
            "{{#create table nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#let a = count(*) from nums}}"
            "{{a}}"
            "{{#insert into nums(value) values (1)}}",
            encoding="utf-8",
        )

        result = await _load_page_async(tmpdir, "count", browser=browser)
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        _, body_text = result

        assert body_text == "1"


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_count_insert_via_execute(browser):
    """Count updates should propagate when inserting after initial load."""
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count_after.pageql").write_text(
            "{{#create table if not exists nums(value INTEGER)}}"
            "{{#reactive on}}"
            "{{#let a = count(*) from nums}}"
            "{{a}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            app.pageql_engine.tables.executeone(
                "INSERT INTO nums(value) VALUES (1)", {}
            )
            await page.wait_for_timeout(10)

        result = await _load_page_async(tmpdir, "count_after", after, reload=True, browser=browser)
        _, body_text = result

        assert body_text == "1"


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_count_delete_via_execute(browser):
    """Count should decrement when a row is deleted via executeone."""

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count_after_delete.pageql").write_text(
            "{{#create table if not exists nums(value INTEGER)}}"
            "{{#insert into nums(value) values (1)}}"
            "{{#reactive on}}"
            "{{#let a = count(*) from nums}}"
            "{{a}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            app.pageql_engine.tables.executeone(
                "DELETE FROM nums WHERE value = 1",
                {},
            )
            await page.wait_for_timeout(10)

        result = await _load_page_async(tmpdir, "count_after_delete", after, reload=True, browser=browser)
        _, body_text = result

        assert body_text == "0"

@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_insert_via_execute_after_click(browser):
    """Inserting via ``executeone`` should display the added text reactively."""

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "msgs.pageql").write_text(
            "{{#create table if not exists msgs(text TEXT)}}"
            "{{#reactive on}}"
            "{{#from msgs}}{{text}}{{/from}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            app.pageql_engine.tables.executeone(
                "INSERT INTO msgs(text) VALUES (:text)", {"text": "hello"}
            )

        result = await _load_page_async(tmpdir, "msgs", after, reload=True, browser=browser)
        _, body_text = result

        assert "hello" in body_text


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_todos_add_partial_in_separate_page(browser):
    """Render todos then invoke the add partial from a second page."""

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(__file__).resolve().parent.parent / "website" / "todos.pageql"
        Path(tmpdir, "todos.pageql").write_text(src.read_text(), encoding="utf-8")

        async def after(page, port, app: PageQLApp):
            page2 = await page.context.browser.new_page()
            await page2.request.post(
                f"http://127.0.0.1:{port}/todos/add",
                data="text=hello",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            await page2.close()
            await page.goto(f"http://127.0.0.1:{port}/todos")

        result = await _load_page_async(tmpdir, "todos", after, reload=True, browser=browser)
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        status, body_text = result

        assert status == 200
        assert "hello" in body_text
