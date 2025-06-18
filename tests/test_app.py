import sys
from pathlib import Path
import types
import tempfile
import http.client
import pageql.pageqlapp
from pageql.http_utils import _http_get
import asyncio
import base64
import html
# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from playwright_helpers import run_server_in_task


def test_app_returns_404_for_missing_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)

            def make_request():
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("GET", "/missing")
                resp = conn.getresponse()
                status = resp.status
                resp.read()
                conn.close()
                return status

            status_inner = await asyncio.to_thread(make_request)

            server.should_exit = True
            await task
            return status_inner

        status = asyncio.run(run_test())

        assert status == 404


def test_render_context_not_saved_on_404():
    with tempfile.TemporaryDirectory() as tmpdir:
        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            app = server.config.app

            def make_request():
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("GET", "/missing")
                resp = conn.getresponse()
                status = resp.status
                resp.read()
                conn.close()
                return status

            status_inner = await asyncio.to_thread(make_request)
            contexts_len = len(app.render_contexts)

            server.should_exit = True
            await task
            return status_inner, contexts_len

        status, contexts_len = asyncio.run(run_test())

        assert status == 404
        assert contexts_len == 0


def test_fallback_app_handles_unknown_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        async def run_test():
            async def fallback(scope, receive, send):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"fallback"})

            server, task, port = await run_server_in_task(tmpdir)
            server.config.app.fallback_app = fallback

            def make_request():
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("GET", "/missing")
                resp = conn.getresponse()
                body = resp.read().decode()
                status = resp.status
                conn.close()
                return status, body

            status_body = await asyncio.to_thread(make_request)

            server.should_exit = True
            await task
            return status_body

        status, body = asyncio.run(run_test())

        assert status == 200
        assert body == "fallback"


def test_fallback_url_handles_unknown_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        async def start_fallback_server():
            async def handler(reader, writer):
                await reader.readline()  # request line
                while await reader.readline() != b"\r\n":
                    pass
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 8\r\n\r\nfallback"
                )
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_server(handler, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            return server, port

        async def run_test():
            fb_server, fb_port = await start_fallback_server()
            server, task, port = await run_server_in_task(tmpdir)
            server.config.app.fallback_url = f"http://127.0.0.1:{fb_port}"

            status, _headers, body = await _http_get(
                f"http://127.0.0.1:{port}/missing"
            )

            server.should_exit = True
            await task
            fb_server.close()
            await fb_server.wait_closed()
            return status, body.decode()

        status, body = asyncio.run(run_test())

        assert status == 200
        assert body == "fallback"


def test_base64_encode_function_is_registered(tmp_path):
    app = pageql.pageqlapp.PageQLApp(":memory:", tmp_path, create_db=True, should_reload=False)
    result = app.conn.execute("select base64_encode(?)", (b'abcd',)).fetchone()[0]
    assert result == base64.b64encode(b'abcd').decode()


def test_query_param_function_is_registered(tmp_path):
    app = pageql.pageqlapp.PageQLApp(":memory:", tmp_path, create_db=True, should_reload=False)
    result = app.conn.execute("select query_param('a=1&b=two', 'b')").fetchone()[0]
    assert result == 'two'
    result_none = app.conn.execute("select query_param('a=1', 'b')").fetchone()[0]
    assert result_none is None


def test_html_escape_function_is_registered(tmp_path):
    app = pageql.pageqlapp.PageQLApp(":memory:", tmp_path, create_db=True, should_reload=False)
    result = app.conn.execute("select html_escape('<div>&')").fetchone()[0]
    assert result == html.escape('<div>&')


def test_before_hook_handles_bytes(tmp_path):
    template = Path(tmp_path) / "before.pageql"
    template.write_text(
        '<img src="data:image/jpeg;base64,{{base64_encode(:image)}}"/>'
    )

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        app = server.config.app

        @app.before("/before")
        async def before_hook(params):
            params["image"] = b"abcd"
            return params

        status, _headers, body = await _http_get(
            f"http://127.0.0.1:{port}/before"
        )
        server.should_exit = True
        await task
        return status, body

    status, body = asyncio.run(run_test())
    assert status == 200
    assert base64.b64encode(b"abcd").decode() in body.decode()


def test_before_all_middleware_modifies_scope(tmp_path):
    (Path(tmp_path) / "index.pageql").write_text("{{ headers.X_Test }}")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        app = server.config.app

        @app.before_all
        def add_header(scope):
            scope.setdefault("headers", []).append((b"X-Test", b"foo"))

        status, _headers, body = await _http_get(f"http://127.0.0.1:{port}/index")
        server.should_exit = True
        await task
        return status, body

    status, body = asyncio.run(run_test())
    assert status == 200
    assert "foo" in body.decode()


def test_index_html_served_when_pageql_missing(tmp_path):
    index_html = Path(tmp_path) / "index.html"
    index_html.write_text("<h1>Home</h1>", encoding="utf-8")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        status, _headers, body_bytes = await _http_get(f"http://127.0.0.1:{port}/")
        server.should_exit = True
        await task
        return status, body_bytes.decode()

    status, body = asyncio.run(run_test())
    assert status == 200
    assert "<h1>Home</h1>" in body

def test_before_template_modifies_params(tmp_path):
    (tmp_path / "_before.pageql").write_text("{{#header X-Test 'hi'}}")
    (tmp_path / "hello.pageql").write_text("ok")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        status, headers, body = await _http_get(f"http://127.0.0.1:{port}/hello")
        server.should_exit = True
        await task
        return status, headers, body.decode()

    status, headers, body = asyncio.run(run_test())
    assert status == 200
    assert (b"x-test", b"hi") in headers


def test_before_template_stops_render_on_error(tmp_path):
    (tmp_path / "_before.pageql").write_text("{{#respond 401 body='no'}}")
    (tmp_path / "hello.pageql").write_text("ok")

    async def run_test():
        server, task, port = await run_server_in_task(str(tmp_path))
        status, _headers, body = await _http_get(f"http://127.0.0.1:{port}/hello")
        server.should_exit = True
        await task
        return status, body.decode()

    status, body = asyncio.run(run_test())
    assert status == 401
    assert "no" in body
