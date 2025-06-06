import os
import time
import tempfile
import asyncio
import threading
import urllib.request
from pageql.pageql import PageQL

ITERATIONS = 100

# port assigned to the local fetch server
FETCH_PORT = 0
# when True the fetch server delays responses
SLOW_FETCH = False

async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await reader.readuntil(b"\r\n\r\n")
    body = b"hi"
    if SLOW_FETCH:
        await asyncio.sleep(0.005)
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nhi")
    await writer.drain()
    writer.close()

def _start_server():
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    server_holder = {}

    async def runner():
        server = await asyncio.start_server(_handle_client, "127.0.0.1", 0)
        server_holder["server"] = server
        server_holder["port"] = server.sockets[0].getsockname()[1]
        ready.set()
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass

    thread = threading.Thread(target=lambda: loop.run_until_complete(runner()), daemon=True)
    thread.start()
    ready.wait()
    return loop, server_holder["server"], server_holder["port"], thread

def _stop_server(loop: asyncio.AbstractEventLoop, server: asyncio.base_events.Server, thread: threading.Thread) -> None:
    """Cleanly stop the background HTTP server."""
    loop.call_soon_threadsafe(server.close)
    thread.join()
    loop.call_soon_threadsafe(loop.close)

def _fetch(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url) as resp:
        return {"body": resp.read().decode(), "status": resp.getcode()}

# helper to reset sample table

def reset_items(db):
    db.execute("DROP TABLE IF EXISTS items")
    db.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    db.executemany("INSERT INTO items(name) VALUES (?)", [("a",), ("b",)])
    db.commit()

# prepare modules with different features
MODULES = {
    's1_static': "Hello",
    's2_expr': "{{1+1}}",
    's3_param': "{{name}}",
    's4_set': "{{#let a = 5}}{{a}}",
    's5_set_expr': "{{#let a = 2}}{{:a + :a}}",
    's6_if': "{{#if 1==1}}yes{{#else}}no{{/if}}",
    's7_ifdef': "{{#ifdef name}}hi{{#else}}bye{{/ifdef}}",
    's8_ifndef': "{{#ifndef name}}hi{{#else}}bye{{/ifndef}}",
    's9_from': "{{#from items}}<{{name}}>{{/from}}",
    's10_nested_from': "{{#from items}}<{{name}}{{#from items}}({{id}}){{/from}}>{{/from}}",
    's11_insert_delete': "{{#insert into items (name) values ('x')}}{{#delete from items where id=1}}",
    'count': "{{count(*) from items}}",
    's12_update': "{{#update items set name='upd' where id=1}}{{#update items set name='upd0' where id=1}}",
    's13_fetch': "{{#fetch d from 'http://127.0.0.1:' || :port}}{{d__body}}",
    's21_slow_fetch': "{{#fetch d from 'http://127.0.0.1:' || :port}}{{d__body}}",
    's14_render_partial': "{{#partial public greet}}hi {{who}}{{/partial}}{{#render greet who='Bob'}}",
    's15_param': "{{#partial public greet}}{{#param who required}}{{who}}{{/partial}}{{#render greet who='Ann'}}",
    's16_create': "{{#create table if not exists t (id int)}}done",
    's17_status': "{{#statuscode 201}}created",
    's18_redirect': "{{#redirect '/target'}}",
    's19_import': "{{#import other as o}}{{#render o}}",
    's20_reactive': "{{#reactive on}}{{#let foo = 1}}{{foo}}",
    'other': "import works",
    'qtest': '''{{#delete from items}}{{#reactive on}}{{#let active_count_reactive = COUNT(*) from items WHERE name = 'x'}}
            {{#insert into items(name) values ('x')}}'''
}

PARAMS = {
    's3_param': {'name': 'Alice'},
    's7_ifdef': {'name': 'x'},
}

# functions for each benchmark

def bench_factory(name):
    def bench(pql):
        params = PARAMS.get(name, {}).copy()
        if name in ('s13_fetch', 's21_slow_fetch'):
            params['port'] = FETCH_PORT
        return pql.render('/' + name, params)
    return bench

SCENARIOS = [(n, bench_factory(n)) for n in MODULES if n != 'other']


def run_benchmarks(db_path):
    global FETCH_PORT, SLOW_FETCH
    loop, server, port, thread = _start_server()
    FETCH_PORT = port
    print(f"Running benchmarks for {db_path} ...")
    pql = PageQL(db_path, fetch_cb=_fetch)
    results = {}
    for name, _ in SCENARIOS:
        reset_items(pql.db)
        for m, src in MODULES.items():
            if m != 'other' and m != name:
                continue
            pql.load_module(m, src)
        bench = bench_factory(name)
        SLOW_FETCH = name == 's21_slow_fetch'
        start = time.perf_counter()
        for _ in range(ITERATIONS):
            bench(pql)
        results[name] = time.perf_counter() - start
    pql.db.close()
    _stop_server(loop, server, thread)
    for k, v in results.items():
        print(f"{k:20s}: {(v/ITERATIONS)*1000:.4f}ms")


async def _run_scenario_parallel(name: str, db_path: str) -> float:
    """Execute one benchmark scenario in parallel and return elapsed time."""

    def _prepare_pql() -> PageQL:
        pql = PageQL(db_path, fetch_cb=_fetch)
        reset_items(pql.db)
        for m, src in MODULES.items():
            if m != 'other' and m != name:
                continue
            pql.load_module(m, src)
        return pql

    async def _call_once() -> None:
        pql = _prepare_pql()
        bench = bench_factory(name)
        try:
            await asyncio.to_thread(bench, pql)
        finally:
            pql.db.close()

    tasks = [asyncio.create_task(_call_once()) for _ in range(ITERATIONS)]
    start = time.perf_counter()
    await asyncio.gather(*tasks)
    return time.perf_counter() - start


def run_benchmarks_parallel(db_path: str) -> None:
    """Run all benchmarks in parallel for each scenario."""
    global FETCH_PORT, SLOW_FETCH
    loop, server, port, thread = _start_server()
    FETCH_PORT = port
    print(f"Running parallel benchmarks for {db_path} ...")
    results = {}
    for name, _ in SCENARIOS:
        SLOW_FETCH = name == 's21_slow_fetch'
        elapsed = asyncio.run(_run_scenario_parallel(name, db_path))
        results[name] = elapsed
    _stop_server(loop, server, thread)
    for k, v in results.items():
        print(f"{k:20s}: {(v/ITERATIONS)*1000:.4f}ms")

if __name__ == '__main__':
    run_benchmarks(':memory:')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'bench.db')
        run_benchmarks(path)
    print("\nParallel version:\n")
    run_benchmarks_parallel(':memory:')
