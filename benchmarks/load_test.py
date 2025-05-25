import os
import subprocess
import tempfile
import time
import shutil
from pathlib import Path
import asyncio
import threading

import uvicorn

from pageql.pageqlapp import PageQLApp


def _run_server(loop: asyncio.AbstractEventLoop, server: uvicorn.Server) -> None:
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())


def start_server(db_file: str, templates_dir: str, port: int):
    """Start the PageQL server in a background thread."""
    app = PageQLApp(db_file, templates_dir, create_db=True, should_reload=False)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_server, args=(loop, server), daemon=True)
    thread.start()

    while not server.started:
        time.sleep(0.05)

    return server, thread, loop


def run_oha(url: str, runs: int = 3) -> None:
    for i in range(runs):
        print(f"oha run {i+1} -> {url}")
        subprocess.run(["oha", "-n", "100", url], check=True)


def load_test(template_file: str, request_path: str, port: int = 8000) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        templates_dir = os.path.join(tmpdir, "templates")
        os.mkdir(templates_dir)
        shutil.copy(template_file, os.path.join(templates_dir, os.path.basename(template_file)))

        server, thread, loop = start_server(db_path, templates_dir, port)
        try:
            run_oha(f"http://localhost:{port}/{request_path}")
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            loop.close()


if __name__ == "__main__":
    # Load test with an empty PageQL file
    with tempfile.TemporaryDirectory() as tmp:
        empty_path = Path(tmp) / "empty.pageql"
        empty_path.touch()  # create 0 byte file
        load_test(str(empty_path), "empty")

    # Load test with the bundled todos example
    todos_path = Path("website") / "todos.pageql"
    load_test(str(todos_path), "todos")
