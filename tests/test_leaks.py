import sys, types, gc, tracemalloc
from pathlib import Path

# Add src and repo root to import PageQL and benchmark helpers
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# Stub watchfiles so it doesn't require optional dependency
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL
from benchmarks.benchmark_pageql import MODULES, SCENARIOS, bench_factory, reset_items

ITERATIONS = 5


def test_render_cleanup_no_leaks(tmp_path):
    db_path = tmp_path / "leak.db"
    pql = PageQL(str(db_path))
    for name, _ in SCENARIOS:
        reset_items(pql.db)
        for m, src in MODULES.items():
            if m != 'other' and m != name:
                continue
            pql.load_module(m, src)
        bench = bench_factory(name)
        # Warm up caches
        result = bench(pql)
        if result.context:
            result.context.cleanup()
        gc.collect()
        tracemalloc.start()
        baseline_objs = len(gc.get_objects())
        baseline_mem = tracemalloc.get_traced_memory()[0]
        for _ in range(ITERATIONS):
            res = bench(pql)
            if res.context:
                res.context.cleanup()
            gc.collect()
        gc.collect()
        after_objs = len(gc.get_objects())
        after_mem = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()
        assert after_objs - baseline_objs == 0
        assert after_mem - baseline_mem == 0
    pql.db.close()
