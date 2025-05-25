import os
import time
import tempfile
from pathlib import Path
from pageql.pageql import PageQL
import cProfile
import pstats
import io

ITERATIONS = 100


def run_benchmark(db_path: str) -> None:
    print(f"Benchmarking todos.pageql using {db_path} ...")
    pql = PageQL(db_path)
    pql.db.execute("CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, completed BOOLEAN)")
    for i in range(10):
        pql.db.execute("INSERT INTO todos (text, completed) VALUES (?, ?)", ("Todo " + str(i), False))
    pql.db.commit()
    src_path = Path(__file__).resolve().parents[1] / "website" / "todos.pageql"
    pql.load_module("todos", src_path.read_text(encoding="utf-8"))

    # Ensure table is created before timing
    pql.render("/todos")
    profiler = cProfile.Profile()
    profiler.enable()
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        pql.render("/todos")
    elapsed = time.perf_counter() - start
    profiler.disable()
    pql.db.close()
    print(f"{(elapsed/ITERATIONS)*1000:.4f}ms per render")
    s = io.StringIO()
    pstats.Stats(profiler, stream=s).strip_dirs().sort_stats("cumulative").print_stats(20)
    print(s.getvalue())


if __name__ == "__main__":
    run_benchmark(":memory:")
    with tempfile.TemporaryDirectory() as tmp:
        run_benchmark(os.path.join(tmp, "bench.db"))
