import sqlite3
from pathlib import Path
import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

import asyncio
import pytest
import pageql.pageqlapp
from pageql.pageql import PageQL, RenderContext
from pageql.reactive import ReactiveTable, Order


def test_infinite_from_adds_order_to_context():
    page = """
    {{#create table items(id INTEGER)}}
    {{#insert into items(id) values (1)}}
    <div>
    {{#from items order by id limit 1 infinite}}
      {{id}}
    {{/from}}
    </div>
    """
    r = PageQL(":memory:")
    r.load_module("test", page)
    result = r.render("/test")
    ctx = result.context
    assert len(ctx.infinites) == 1
    order = list(ctx.infinites.values())[0]
    assert isinstance(order, Order)
    assert order.limit == 1


def test_pageqlapp_handles_infinite_load_more(tmp_path):
    app = pageql.pageqlapp.PageQLApp(":memory:", tmp_path, create_db=True, should_reload=False)

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items(id INTEGER)")
    conn.executemany("INSERT INTO items(id) VALUES (?)", [(1,), (2,), (3,)])
    rt = ReactiveTable(conn, "items")
    order = Order(rt, "id", limit=1)

    ctx = RenderContext()
    mid = ctx.marker_id()
    ctx.infinites[mid] = order
    app.render_contexts["cid"].append(ctx)

    messages = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": f"infinite_load_more {mid}"},
        {"type": "websocket.disconnect"},
    ]

    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return messages.pop(0)

    scope = {"type": "websocket", "path": "/reload-request-ws", "query_string": b"clientId=cid"}

    async def run_ws():
        await app._handle_reload_websocket(scope, receive, send)

    asyncio.run(run_ws())

    assert order.limit == 101


def test_infinite_load_more_error_sends_ws(tmp_path):
    app = pageql.pageqlapp.PageQLApp(
        ":memory:", tmp_path, create_db=True, should_reload=False
    )

    ctx = RenderContext()
    app.render_contexts["cid"].append(ctx)

    messages = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": "infinite_load_more 123"},
        {"type": "websocket.disconnect"},
    ]

    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return messages.pop(0)

    scope = {
        "type": "websocket",
        "path": "/reload-request-ws",
        "query_string": b"clientId=cid",
    }

    async def run_ws():
        await app._handle_reload_websocket(scope, receive, send)

    asyncio.run(run_ws())

    assert any(
        m.get("type") == "websocket.send" and "console.error" in m.get("text", "")
        for m in sent
    )
