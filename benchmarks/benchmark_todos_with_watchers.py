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
TOGGLE_ITERATIONS = 10


def run_benchmark(db_path: str) -> None:
    print(f"Benchmarking todos.pageql watchers using {db_path} ...")
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
    for i in range(TOGGLE_ITERATIONS):
        tid = (i % INSERTS) + 1
        pql.render("/todos", partial=f"{tid}/toggle", http_verb="POST")
    elapsed = time.perf_counter() - start
    profiler.disable()

    pql.db.close()
    assert len(ctxs) == RENDER_WATCHERS
    s = io.StringIO()
    pstats.Stats(profiler, stream=s).strip_dirs().sort_stats("cumulative").print_stats(20)
    print(s.getvalue())
    assert len(ctxs[0].scripts) == TOGGLE_ITERATIONS * 2 + 1
    print(f"{(elapsed/TOGGLE_ITERATIONS)*1000:.4f}ms per toggle")
    total_messages = RENDER_WATCHERS * TOGGLE_ITERATIONS
    messages_per_second = total_messages / elapsed
    print(f"{messages_per_second:.0f} messages/second")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        run_benchmark(os.path.join(tmp, "bench.db"))
