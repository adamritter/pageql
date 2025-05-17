import sys
from pathlib import Path
import types
import tempfile
import socket
import time
import http.client
from multiprocessing import Process
from uvicorn.config import Config
from uvicorn.server import Server

# Ensure the package can be imported without optional dependencies
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


def test_app_returns_404_for_missing_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)

        port = _get_free_port()

        def serve():
            app2 = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
            config = Config(app2, host="127.0.0.1", port=port, log_level="warning")
            Server(config).run()

        proc = Process(target=serve)
        proc.start()

        # Wait for the server to accept connections
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
        conn.request("GET", "/missing")
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()

        proc.terminate()
        proc.join()

        assert status == 404


if __name__ == "__main__":
    test_app_returns_404_for_missing_route()
