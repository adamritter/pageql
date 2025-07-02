import sys
import importlib.util
import tempfile
import asyncio
from pathlib import Path
import pytest

pytestmark = pytest.mark.anyio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))



from pageql.pageqlapp import PageQLApp
from playwright_helpers import _load_page_async, run_server_in_task

pytest.importorskip("playwright.async_api")
from playwright.async_api import async_playwright

@pytest.fixture(scope="module")
async def setup():
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    print("launched")

    yield browser  # ← your tests can now use this browser

    await browser.close()
    await playwright.stop()


async def start_server(tmpdir: str, reload: bool = False):
    server, task, port = await run_server_in_task(tmpdir, reload)
    app: PageQLApp = server.config.app
    return server, task, port, app

@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_hello_world_in_browser(setup):

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "hello.pageql").write_text(
            "{%header X-Test 'v'%}Hello world!", encoding="utf-8"
        )

        server, task, port, app = await start_server(tmpdir)

        page = await setup.new_page()
        response = await page.goto(f"http://127.0.0.1:{port}/hello")
        body_text = await response.text()

        assert response.status == 200
        assert response.headers.get("x-test") == "v"
        assert "Hello world!" in body_text

        await page.close()
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_set_variable_in_browser(setup):
    """Ensure directives work when rendered through the ASGI app."""

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "greet.pageql").write_text("{%let :a = 'world'%}Hello {{a}}", encoding="utf-8")

        server, task, port, app = await start_server(tmpdir)
        result = await _load_page_async(port, "greet", app, browser=setup)
        status, body_text, client_id = result

        assert status == 200
        assert "Hello world" in body_text
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_set_variable_in_browser(setup):
    """Ensure reactive mode updates are sent to the browser."""
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "react.pageql").write_text(
            "{%create table vars(val TEXT)%}"
            "{%insert into vars(val) values ('ww')%}"
            "{%reactive on%}"
            "{%let a = (select val from vars)%}"
            "hello {{a}}"
            "{%update vars set val = 'world'%}",
            encoding="utf-8",
        )

        server, task, port, app = await start_server(tmpdir)
        body_text = await _load_page_async(port, "react", app, browser=setup)
        _, text, client_id = body_text

        assert text == "hello world"
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_count_insert_in_browser(setup):
    """Count updates should be delivered to the browser when rows are inserted."""
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count.pageql").write_text(
            "{%create table nums(value INTEGER)%}"
            "{%reactive on%}"
            "{%let a = count(*) from nums%}"
            "{{a}}"
            "{%insert into nums(value) values (1)%}",
            encoding="utf-8",
        )

        server, task, port, app = await start_server(tmpdir)
        result = await _load_page_async(port, "count", app, browser=setup)
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        _, body_text, client_id = result

        assert body_text == "1"
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_count_insert_via_execute(setup):
    """Count updates should propagate when inserting after initial load."""
    if (
        importlib.util.find_spec("websockets") is None
        and importlib.util.find_spec("wsproto") is None
    ):
        pytest.skip("WebSocket library not available for reactive test")

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count_after.pageql").write_text(
            "{%create table if not exists nums(value INTEGER)%}"
            "{%reactive on%}"
            "{%let a = count(*) from nums%}"
            "{{a}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            app.pageql_engine.tables.executeone(
                "INSERT INTO nums(value) VALUES (1)", {}
            )

        server, task, port, app = await start_server(tmpdir, reload=True)
        result = await _load_page_async(port, "count_after", app, after, browser=setup)
        _, body_text, client_id = result
        body_text = (await app.get_text_body(client_id)).strip()

        assert body_text == "1"
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_reactive_count_delete_via_execute(setup):
    """Count should decrement when a row is deleted via executeone."""

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "count_after_delete.pageql").write_text(
            "{%create table if not exists nums(value INTEGER)%}"
            "{%insert into nums(value) values (1)%}"
            "{%reactive on%}"
            "{%let a = count(*) from nums%}"
            "{{a}}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            app.pageql_engine.tables.executeone(
                "DELETE FROM nums WHERE value = 1",
                {},
            )

        server, task, port, app = await start_server(tmpdir, reload=True)
        result = await _load_page_async(port, "count_after_delete", app, after, browser=setup)
        _, body_text, client_id = result

        assert body_text == "0"
        server.should_exit = True
        await task

@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_insert_via_execute_after_click(setup):
    """Inserting via ``executeone`` should display the added text reactively."""

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "msgs.pageql").write_text(
            "{%create table if not exists msgs(text TEXT)%}"
            "{%reactive on%}"
            "{%from msgs%}{{text}}{%endfrom%}",
            encoding="utf-8",
        )

        async def after(page, port, app: PageQLApp):
            app.pageql_engine.tables.executeone(
                "INSERT INTO msgs(text) VALUES (:text)", {"text": "hello"}
            )

        server, task, port, app = await start_server(tmpdir, reload=True)
        result = await _load_page_async(port, "msgs", app, after, browser=setup)
        _, body_text, client_id = result

        assert "hello" in body_text
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_todos_add_partial_in_separate_page(setup):
    """Render todos then invoke the add partial from a second page."""
    new_body = None

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
            nonlocal new_body
            new_body = await page.goto(f"http://127.0.0.1:{port}/todos")

        server, task, port, app = await start_server(tmpdir, reload=True)
        result = await _load_page_async(port, "todos", app, after, browser=setup)
        if result is None:
            pytest.skip("Chromium not available for Playwright")
        status, body_text, client_id = result

        assert status == 200
        assert "hello" in (await new_body.text()).strip()
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_get_text_body_from_client(setup):
    """Server should retrieve body text via WebSocket from the client."""

    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "hello.pageql").write_text("Hello world!", encoding="utf-8")

        server, task, port, app = await start_server(tmpdir)

        page = await setup.new_page()
        response = await page.goto(
            f"http://127.0.0.1:{port}/hello?clientId=testcid"
        )

        body_via_app = await app.get_text_body("testcid")

        assert response.status == 200
        assert "Hello world!" in body_via_app

        await page.close()
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_fetch_async_directive_in_browser(setup):
    """Async fetch should update the page once the HTTP request completes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "data.pageql").write_text("hello", encoding="utf-8")
        Path(tmpdir, "fetch.pageql").write_text(
            "{%fetch async d from 'http://127.0.0.1:'||:port||'/data'%}{{d__body}}",
            encoding="utf-8",
        )

        server, task, port, app = await start_server(tmpdir)
        result = await _load_page_async(port, f"fetch?port={port}", app, browser=setup)
        status, body_text, client_id = result

        assert status == 200
        assert "hello" in body_text
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_fetch_async_healthz_in_browser(setup):
    """Async fetch should resolve relative URLs using the request host."""
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "fetchrel.pageql").write_text(
            "{%fetch async d from '/healthz'%}"
            "{%if :d.status_code == 200%}"
            "{%fetch async d2 from '/healthz'%}"
            "{{d2__body}}"
            "{{/fetch}}"
            "{%else%}Loading...{%endif%}"
            "{{/fetch}}",
            encoding="utf-8",
        )

        server, task, port, app = await start_server(tmpdir)
        result = await _load_page_async(port, "fetchrel", app, browser=setup)
        status, body_text, client_id = result
        assert status == 200
        assert "OK" in body_text
        server.should_exit = True
        await task


@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_json_page_in_browser(setup):
    """Render the json.pageql template and verify JSON output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(__file__).resolve().parent.parent / "website" / "json.pageql"
        Path(tmpdir, "json.pageql").write_text(src.read_text(), encoding="utf-8")

        server, task, port, app = await start_server(tmpdir)

        app.conn.execute(
            "CREATE TABLE IF NOT EXISTS todos(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, completed INTEGER DEFAULT 0 CHECK(completed IN (0,1)))"
        )
        app.conn.execute("INSERT INTO todos(text) VALUES ('task')")
        app.conn.commit()

        page = await setup.new_page()
        response = await page.goto(f"http://127.0.0.1:{port}/json")
        body_text = await response.text()

        assert response.status == 200
        assert response.headers.get("content-type") == "application/json"

        import json

        data = json.loads(body_text)
        assert data == [
            [{"id": 1, "text": "task", "completed": 0}],
            [{"id": 1, "text": "task", "completed": 0}],
        ]

        await page.close()
        server.should_exit = True
        await task

@pytest.mark.filterwarnings("ignore:.*:DeprecationWarning")
async def test_pset_with_script_tags(setup):
    """pset should execute nested scripts to update the DOM correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "pset.pageql").write_text(
            (
                "{%create table if not exists todos (id integer primary key autoincrement, text text)%}"
                "{%delete from todos%}"
                "{%let todos_count = (select count(*) from todos)%}"
                "{%if :todos_count > 0%}"
                "{{todos_count}}"
                "{%endif%}"
                "{%insert into todos (text) values ('Hello, world!')%}"
            ),
            encoding="utf-8",
        )

        server, task, port, app = await start_server(tmpdir)
        result = await _load_page_async(port, "pset", app, browser=setup)
        status, body_text, client_id = result

        assert status == 200
        assert body_text.strip() == "1"
        server.should_exit = True
        await task



