import os
import subprocess
import tempfile
import time
import shutil
from pathlib import Path


def start_server(db_file: str, templates_dir: str, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    src_path = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = str(src_path) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        "python",
        "-u",
        str(src_path / "pageql" / "cli.py"),
        db_file,
        templates_dir,
        "--port",
        str(port),
        "--create",
        "--no-reload",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


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

        proc = start_server(db_path, templates_dir, port)
        try:
            time.sleep(1)  # wait for server to start
            run_oha(f"http://localhost:{port}/{request_path}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    # Load test with an empty PageQL file
    with tempfile.TemporaryDirectory() as tmp:
        empty_path = Path(tmp) / "empty.pageql"
        empty_path.touch()  # create 0 byte file
        load_test(str(empty_path), "empty")

    # Load test with the bundled todos example
    todos_path = Path("website") / "todos.pageql"
    load_test(str(todos_path), "todos")
