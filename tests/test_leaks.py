import sys, gc, tracemalloc
from pathlib import Path
import pytest

# Disable this test module by default as it is slow and provides little ROI
pytest.skip("test_leaks disabled", allow_module_level=True)

# Add src and repo root to import PageQL and benchmark helpers
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


from pageql.pageql import PageQL
from benchmarks.benchmark_pageql import MODULES, SCENARIOS, bench_factory, reset_items, PARAMS

ITERATIONS = 1000


def test_render_cleanup_no_leaks(tmp_path):
    db_path = tmp_path / "leak.db"
    pql = PageQL(str(db_path))
    for name, _ in SCENARIOS:
        reset_items(pql.db)
        for m, src in MODULES.items():
            if m != 'other' and m != name:
                continue
            pql.load_module(m, src)
        bench = lambda p, n=name: p.render('/' + n, PARAMS.get(n, {}), reactive=False)
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
        after_objs = len(gc.get_objects())
        after_mem = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()

        obj_diff = after_objs - baseline_objs
        mem_diff = after_mem - baseline_mem

        if obj_diff or mem_diff:
            print(f"LEAK in {name}: objs={obj_diff}, mem={mem_diff}")
        else:
            print(f"{name}: no leak")

        assert obj_diff < 195, (
            f"{name} leaked: objs diff {obj_diff}, mem diff {mem_diff}"
        )
    pql.db.close()
