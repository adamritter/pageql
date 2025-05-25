import os
import time
import tempfile
from pathlib import Path
from pageql.pageql import PageQL

ITERATIONS = 100


def run_benchmark(db_path: str) -> None:
    print(f"Benchmarking todos.pageql using {db_path} ...")
    pql = PageQL(db_path)
    src_path = Path(__file__).resolve().parents[1] / "website" / "todos.pageql"
    pql.load_module("todos", src_path.read_text(encoding="utf-8"))

    # Ensure table is created before timing
    pql.render("/todos")
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        pql.render("/todos")
    elapsed = time.perf_counter() - start
    pql.db.close()
    print(f"{(elapsed/ITERATIONS)*1000:.4f}ms per render")


if __name__ == "__main__":
    run_benchmark(":memory:")
    with tempfile.TemporaryDirectory() as tmp:
        run_benchmark(os.path.join(tmp, "bench.db"))
