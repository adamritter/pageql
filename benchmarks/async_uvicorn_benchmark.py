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

    # Wait until the server is responsive. Occasionally ``server.started`` is
    # ``True`` before the socket is fully accepting connections.
    while True:
        try:
            await _http_get(f"http://127.0.0.1:{port}/todos")
            break
        except ConnectionRefusedError:
            await asyncio.sleep(0.05)


    # warmup and extract client id
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
        asyncio.create_task(
            _http_get(
                f"http://127.0.0.1:{port}/todos/add",
                method="POST",
                headers={
                    "ClientId": client_id,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                if client_id
                else {"Content-Type": "application/x-www-form-urlencoded"},
                body=f"text=bench{i}".encode(),
            )
        )
        for i in range(TODO_COUNT)
    ]
    await asyncio.gather(*post_tasks)

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

    for ws in websocket_connections:
        try:
            await ws.close()
        except Exception:
            pass


async def run_fetch_only_benchmark(
    http_disconnect_cleanup_timeout=None,
    parallel=True,
    iterations=REQUEST_ITERATIONS,
) -> None:
    """Start the server and fetch the todos page concurrently."""
    templates_dir = Path(__file__).resolve().parents[1] / "website"
    app = PageQLApp(
        ":memory:",
        str(templates_dir),
        create_db=True,
        should_reload=True,
        quiet=True,
        http_disconnect_cleanup_timeout=http_disconnect_cleanup_timeout,
    )
    config = Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = Server(config)

    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    assert server.servers and server.servers[0].sockets
    port = server.servers[0].sockets[0].getsockname()[1]

    await _http_get(f"http://127.0.0.1:{port}/todos")

    # Insert some sample todos before timing the page fetches
    app.db = app.conn
    for i in range(10):
        app.db.execute(
            "INSERT INTO todos (text, completed) VALUES (?, 0)",
            (f"Todo {i}",),
        )
    app.db.commit()

    start = time.perf_counter()
    if parallel:
        tasks = [
            asyncio.create_task(
                _http_get(f"http://127.0.0.1:{port}/todos")
            )
            for _ in range(iterations)
        ]
        results = await asyncio.gather(*tasks)
    else:
        results = []
        for _ in range(iterations):
            results.append(await _http_get(f"http://127.0.0.1:{port}/todos"))
    elapsed = time.perf_counter() - start
    print(f"Gather fetch {iterations/elapsed:.0f} QPS, iterations: {iterations}, http_disconnect_cleanup_timeout: {http_disconnect_cleanup_timeout}")

    server.should_exit = True
    await server_task

    return results


if __name__ == "__main__":
    asyncio.run(run_fetch_only_benchmark(http_disconnect_cleanup_timeout=0.05, parallel=False, iterations=10000))
    asyncio.run(run_fetch_only_benchmark(http_disconnect_cleanup_timeout=10, parallel=False, iterations=10000))
    asyncio.run(run_benchmark())

