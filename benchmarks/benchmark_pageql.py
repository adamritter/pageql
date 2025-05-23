import os
import time
import tempfile
from pageql.pageql import PageQL

ITERATIONS = 100

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
    's4_set': "{{#set a 5}}{{a}}",
    's5_set_expr': "{{#set a 2}}{{:a + :a}}",
    's6_if': "{{#if 1==1}}yes{{#else}}no{{/if}}",
    's7_ifdef': "{{#ifdef name}}hi{{#else}}bye{{/ifdef}}",
    's8_ifndef': "{{#ifndef name}}hi{{#else}}bye{{/ifndef}}",
    's9_from': "{{#from items}}<{{name}}>{{/from}}",
    's10_nested_from': "{{#from items}}<{{name}}{{#from items}}({{id}}){{/from}}>{{/from}}",
    's11_insert_delete': "{{#insert into items (name) values ('x')}}{{#delete from items where id=1}}",
    'count': "{{count(*) from items}}",
    's12_update': "{{#update items set name='upd' where id=1}}{{#update items set name='upd0' where id=1}}",
    's14_render_partial': "{{#partial public greet}}hi {{who}}{{/partial}}{{#render greet who='Bob'}}",
    's15_param': "{{#partial public greet}}{{#param who required}}{{who}}{{/partial}}{{#render greet who='Ann'}}",
    's16_create': "{{#create table if not exists t (id int)}}done",
    's17_status': "{{#statuscode 201}}created",
    's18_redirect': "{{#redirect '/target'}}",
    's19_import': "{{#import other as o}}{{#render o}}",
    's20_reactive': "{{#reactive on}}{{#set foo 1}}{{foo}}",
    'other': "import works",
    'qtest': '''{{#delete from items}}{{#reactive on}}{{#set active_count_reactive COUNT(*) from items WHERE name = 'x'}}
            {{#insert into items(name) values ('x')}}'''
}

PARAMS = {
    's3_param': {'name': 'Alice'},
    's7_ifdef': {'name': 'x'},
}

# functions for each benchmark

def bench_factory(name):
    def bench(pql):
        return pql.render('/'+name, PARAMS.get(name, {}))
    return bench

SCENARIOS = [(n, bench_factory(n)) for n in MODULES if n != 'other']


def run_benchmarks(db_path):
    print(f"Running benchmarks for {db_path} ...")
    pql = PageQL(db_path)
    results = {}
    for name, _ in SCENARIOS:
        reset_items(pql.db)
        for m, src in MODULES.items():
            if m != 'other' and m != name:
                continue
            pql.load_module(m, src)
        bench = bench_factory(name)
        start = time.perf_counter()
        for _ in range(ITERATIONS):
            bench(pql)
        results[name] = time.perf_counter() - start
    pql.db.close()
    for k, v in results.items():
        print(f"{k:20s}: {(v/ITERATIONS)*1000:.4f}ms")

if __name__ == '__main__':
    run_benchmarks(':memory:')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'bench.db')
        run_benchmarks(path)
