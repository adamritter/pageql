import os
import time
import tempfile
from pathlib import Path
from pageql.pageql import PageQL
import cProfile
import pstats
import io

RENDER_WATCHERS = 1000
INSERTS = 200
TOGGLE_ALL_ITERATIONS = 10


def run_benchmark(db_path: str) -> None:
    print(f"Benchmarking todos.pageql toggle_all watchers using {db_path} ...")
    pql = PageQL(db_path)
    pql.db.execute(
        "CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, completed BOOLEAN)"
    )
    pql.db.commit()
    src_path = Path(__file__).resolve().parents[1] / "website" / "todos.pageql"
    pql.load_module("todos", src_path.read_text(encoding="utf-8"))

    # create watchers
    ctxs = []
    for _ in range(RENDER_WATCHERS):
        ctxs.append(pql.render("/todos", reactive=True).context)
    # insert todos
    for i in range(INSERTS):
        pql.db.execute(
            "INSERT INTO todos (text, completed) VALUES (?, 0)",
            (f"Todo {i}",),
        )
    pql.db.commit()

    profiler = cProfile.Profile()
    profiler.enable()
    start = time.perf_counter()
    for _ in range(TOGGLE_ALL_ITERATIONS):
        pql.render("/todos", partial="toggle_all", http_verb="POST")
    elapsed = time.perf_counter() - start
    profiler.disable()

    pql.db.close()
    assert len(ctxs) == RENDER_WATCHERS
    s = io.StringIO()
    pstats.Stats(profiler, stream=s).strip_dirs().sort_stats("cumulative").print_stats(20)
    print(s.getvalue())
    assert len(ctxs[0].scripts) == 0
    print(f"{(elapsed/TOGGLE_ALL_ITERATIONS)*1000:.4f}ms per toggle_all")
    total_messages = RENDER_WATCHERS * TOGGLE_ALL_ITERATIONS
    messages_per_second = total_messages / elapsed
    print(f"{messages_per_second:.0f} messages/second")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        run_benchmark(os.path.join(tmp, "bench.db"))
