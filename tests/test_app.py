import sys
from pathlib import Path
import types
import tempfile
import http.client
import http.server
import threading
import pageql.pageqlapp
from pageql.http_utils import _http_get
import asyncio
import base64
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
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"fallback")

            def log_message(self, *args):
                pass

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        fb_port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever)
        thread.daemon = True
        thread.start()

        async def run_test():
            server, task, port = await run_server_in_task(tmpdir)
            server.config.app.fallback_url = f"http://127.0.0.1:{fb_port}"

            async def make_request():
                status, _headers, body = await _http_get(
                    f"http://127.0.0.1:{port}/missing"
                )
                return status, body.decode()

            status_body = await make_request()

            server.should_exit = True
            await task
            httpd.shutdown()
            thread.join()
            return status_body

        status, body = asyncio.run(run_test())

        assert status == 200
        assert body == "fallback"


def test_base64_encode_function_is_registered(tmp_path):
    app = pageql.pageqlapp.PageQLApp(":memory:", tmp_path, create_db=True, should_reload=False)
    result = app.conn.execute("select base64_encode(?)", (b'abcd',)).fetchone()[0]
    assert result == base64.b64encode(b'abcd').decode()


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

