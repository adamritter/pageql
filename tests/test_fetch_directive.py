import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.parser import tokenize, build_ast, ast_param_dependencies
from pageql.pageql import PageQL
import sqlite3
import pytest


def test_fetch_directive_parsed():
    tokens = tokenize("{{#fetch file from 'http://ex'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'", False))]


def test_fetch_async_directive_parsed():
    tokens = tokenize("{{#fetch async file from 'http://ex'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'", True))]


def test_fetch_directive_dependencies():
    tokens = tokenize("{{#fetch dst from :url}}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"url"}


def test_fetch_async_directive_dependencies():
    tokens = tokenize("{{#fetch async dst from :url}}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"url"}


def test_fetch_directive_render():
    seen = []

    def fetch(url: str):
        seen.append(url)
        return {"a": "1", "b": "2"}

    from pageql import pageql as pql_mod
    old_fetch = pql_mod.fetch_sync
    pql_mod.fetch_sync = fetch
    try:
        r = PageQL(":memory:")
        r.load_module("m", "{{#fetch data from 'http://x'}}{{data__a}} {{data__b}}")
        out = r.render("/m", reactive=False).body
    finally:
        pql_mod.fetch_sync = old_fetch
    assert out.strip() == "1 2"
    assert seen == ["http://x"]


def test_fetch_directive_defaults_to_http_get():
    import http.server, threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hi"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.start()
    try:
        r = PageQL(":memory:")
        r.load_module(
            "m",
            "{{#fetch d from 'http://127.0.0.1:' || :port}}{{d__status_code}} {{d__body}}",
        )
        out = r.render("/m", {"port": port}, reactive=False).body.strip()
        assert out == "200 hi"
    finally:
        server.shutdown()
        t.join()


def test_fetch_commits_before_call(tmp_path):
    db_file = tmp_path / "db.sqlite"

    def fetch(_url: str):
        with sqlite3.connect(db_file) as c2:
            return {"cnt": c2.execute("select count(*) from t").fetchone()[0]}

    from pageql import pageql as pql_mod
    old_fetch = pql_mod.fetch_sync
    pql_mod.fetch_sync = fetch
    try:
        r = PageQL(str(db_file))
        r.load_module(
            "m",
            """{{#create table t(x int)}}{{#insert into t values (1)}}{{#fetch d from 'x'}}{{d__cnt}}""",
        )
        out = r.render("/m", reactive=False).body.strip()
    finally:
        pql_mod.fetch_sync = old_fetch
    assert out == "1"



