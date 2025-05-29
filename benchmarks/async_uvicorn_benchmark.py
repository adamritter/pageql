import asyncio
import time
import re
from pathlib import Path

from uvicorn.config import Config
from uvicorn.server import Server

from pageql.pageqlapp import PageQLApp
import websockets


async def _read_chunked_body(reader: asyncio.StreamReader) -> bytes:
    chunks = []
    while True:
        size_line = await reader.readline()
        size = int(size_line.strip(), 16)
        if size == 0:
            await reader.readline()  # trailing CRLF after last chunk
            break
        chunk = await reader.readexactly(size)
        chunks.append(chunk)
        await reader.readline()  # CRLF after each chunk
    return b"".join(chunks)


async def fetch(host: str, port: int, path: str, *, return_body: bool = False):
    reader, writer = await asyncio.open_connection(host, port)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Connection: keep-alive\r\n"
        "\r\n"
    )
    writer.write(request.encode())
    await writer.drain()

    # parse status line and headers
    await reader.readline()  # status line
    headers = {}
    while True:
        line = await reader.readline()
        if line == b"\r\n":
            break
        key, val = line.decode().split(":", 1)
        headers[key.strip().lower()] = val.strip()

    body = None
    if return_body:
        if headers.get("transfer-encoding") == "chunked":
            body_bytes = await _read_chunked_body(reader)
        elif "content-length" in headers:
            length = int(headers["content-length"])
            body_bytes = await reader.readexactly(length)
        else:
            body_bytes = await reader.read()  # fallback
        body = body_bytes.decode()

    return reader, writer, body


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

    # warmup and extract client id
    connections = []
    websocket_connections = []

    reader, writer, body = await fetch("127.0.0.1", port, "/todos", return_body=True)
    connections.append((reader, writer))

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
    for _ in range(10000):
        reader, writer, body = await fetch("127.0.0.1", port, "/todos", return_body=True)
        connections.append((reader, writer))
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

    print(f"{10000/elapsed:.2f} QPS")

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

