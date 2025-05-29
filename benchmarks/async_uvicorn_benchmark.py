import asyncio
import time
import re
from pathlib import Path

from uvicorn.config import Config
from uvicorn.server import Server

from pageql.pageqlapp import PageQLApp


async def fetch(host: str, port: int, path: str, *, return_body: bool = False):
    reader, writer = await asyncio.open_connection(host, port)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    writer.write(request.encode())
    await writer.drain()
    data = await reader.read()
    writer.close()
    await writer.wait_closed()
    if return_body:
        body = data.split(b"\r\n\r\n", 1)[-1]
        return body.decode()
    return None


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
    body = await fetch("127.0.0.1", port, "/todos", return_body=True)
    match = re.search(r"const clientId = \"([^\"]+)\"", body)
    if match:
        client_id = match.group(1)
        print(f"Client ID: {client_id}")
    else:
        print("Client ID not found")
    start = time.perf_counter()
    for _ in range(10000):
        await fetch("127.0.0.1", port, "/todos")
    elapsed = time.perf_counter() - start

    print(f"{10000/elapsed:.2f} QPS")

    server.should_exit = True
    await server_task


if __name__ == "__main__":
    asyncio.run(run_benchmark())

