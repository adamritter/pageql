import sys
from pathlib import Path
import types
import tempfile
import asyncio

# Minimal ASGI test helper
async def asgi_get(app, path="/"):
    messages = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
    }

    await app(scope, receive, send)
    return messages


# Ensure the package can be imported without optional dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageqlapp import PageQLApp


def test_app_returns_404_for_missing_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        app = PageQLApp(":memory:", tmpdir, create_db=True, should_reload=False)
        messages = asyncio.run(asgi_get(app, "/missing"))
        # first message should be http.response.start
        assert messages[0]["status"] == 404
