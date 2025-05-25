import os
import tempfile
import shutil
import time
import asyncio
import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn
from locust import HttpUser, task, constant
from locust.env import Environment
from locust.stats import stats_printer
import gevent

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


def run_locust(template_file: str, request_path: str, port: int = 8000, users: int = 10, runtime: int = 3) -> None:
    class PageQLUser(HttpUser):
        host = f"http://localhost:{port}"
        wait_time = constant(0)

        @task
        def load(self):
            self.client.get(f"/{request_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        templates_dir = os.path.join(tmpdir, "templates")
        os.mkdir(templates_dir)
        shutil.copy(template_file, os.path.join(templates_dir, os.path.basename(template_file)))

        server, thread, loop = start_server(db_path, templates_dir, port)
        try:
            env = Environment(user_classes=[PageQLUser])
            env.create_local_runner()
            env.runner.start(users, spawn_rate=users)
            gevent.spawn(stats_printer(env.stats))
            gevent.sleep(runtime)
            env.runner.quit()
            print("Total requests:", env.stats.total.num_requests)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            loop.close()


if __name__ == "__main__":
    # Load test with an empty PageQL file
    with tempfile.TemporaryDirectory() as tmp:
        empty_path = Path(tmp) / "empty.pageql"
        empty_path.touch()  # create 0 byte file
        run_locust(str(empty_path), "empty")

    # Load test with the bundled todos example
    todos_path = Path("website") / "todos.pageql"
    run_locust(str(todos_path), "todos")


