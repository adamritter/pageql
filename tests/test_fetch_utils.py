import asyncio
import http.server
import threading

import pytest
from pageql.http_utils import fetch


def test_fetch_relative_url():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.start()
    try:
        result = asyncio.run(fetch("/healthz", base_url=f"http://127.0.0.1:{port}"))
        assert result["status_code"] == 200
        assert result["body"] == "ok"
    finally:
        server.shutdown()
        t.join()


def test_fetch_relative_url_without_base_url_raises():
    with pytest.raises(ValueError):
        asyncio.run(fetch("/bad"))
