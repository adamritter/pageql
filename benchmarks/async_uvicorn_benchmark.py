import asyncio
import time
import re
from pathlib import Path

from uvicorn.config import Config
from uvicorn.server import Server

from pageql.pageqlapp import PageQLApp
from pageql.http_utils import _http_get
import websockets

# number of HTTP requests to issue when measuring request/response throughput
REQUEST_ITERATIONS = 1000

# number of todo items inserted and websocket messages drained
TODO_COUNT = 30




async def run_benchmark() -> None:
    templates_dir = Path(__file__).resolve().parents[1] / "website"
    app = PageQLApp(
        ":memory:",
        str(templates_dir),
        create_db=True,
        should_reload=True,
        quiet=True,
    )
    config = Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = Server(config)

    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    assert server.servers and server.servers[0].sockets
    port = server.servers[0].sockets[0].getsockname()[1]

    async def post_todo(text: str, cid: str | None) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        headers = {"ClientId": cid} if cid else {}
        body_bytes = text.encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        headers.setdefault("Content-Length", str(len(body_bytes)))
        header_lines = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        request = (
            "POST /todos/add HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"{header_lines}"
            "Connection: keep-alive\r\n"
            "\r\n"
        )
        writer.write(request.encode() + body_bytes)
        await writer.drain()
        await reader.readline()  # status line
        while True:
            line = await reader.readline()
            if line == b"\r\n":
                break
        return reader, writer

    # warmup and extract client id
    connections = []
    websocket_connections = []

    client_id = None
    _status, _headers, body_bytes = await _http_get(f"http://127.0.0.1:{port}/todos")
    body = body_bytes.decode()

    match = re.search(r"const clientId = \"([^\"]+)\"", body)
    if match:
        client_id = match.group(1)
        print(f"Client ID: {client_id}")
        ws_url = f"ws://127.0.0.1:{port}/reload-request-ws?clientId={client_id}"
        try:
            ws = await websockets.connect(ws_url)
            websocket_connections.append(ws)
        except Exception as exc:
            print(f"Failed to connect WS: {exc}")
    else:
        print("Client ID not found")

    start = time.perf_counter()
    for _ in range(REQUEST_ITERATIONS):
        _status, _headers, body_bytes = await _http_get(
            f"http://127.0.0.1:{port}/todos"
        )
        body = body_bytes.decode()
        match = re.search(r"const clientId = \"([^\"]+)\"", body)
        if match:
            cid = match.group(1)
            ws_url = f"ws://127.0.0.1:{port}/reload-request-ws?clientId={cid}"
            try:
                ws = await websockets.connect(ws_url)
                websocket_connections.append(ws)
            except Exception:
                pass
    elapsed = time.perf_counter() - start

    print(f"{REQUEST_ITERATIONS/elapsed:.0f} QPS")

    # insert multiple todos concurrently and wait for websocket updates
    start = time.perf_counter()
    post_tasks = [
        asyncio.create_task(post_todo(f"text=bench{i}", client_id))
        for i in range(TODO_COUNT)
    ]
    results = await asyncio.gather(*post_tasks)
    for r, w in results:
        connections.append((r, w))

    recvs = 0
    async def drain_ws(ws):
        nonlocal recvs
        a=""
        while f"/todos/{TODO_COUNT}" not in a:
            a = await ws.recv()
            recvs += 1

    await asyncio.gather(*(drain_ws(ws) for ws in websocket_connections))
    ws_elapsed = time.perf_counter() - start
    total_msgs = len(websocket_connections) * TODO_COUNT
    print(f"{total_msgs/ws_elapsed:.0f} WS QPS")
    print(f"Batch size: {total_msgs/recvs:.0f}")

    server.should_exit = True
    await server_task

    for r, w in connections:
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass

    for ws in websocket_connections:
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(run_benchmark())

