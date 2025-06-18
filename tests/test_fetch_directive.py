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
    assert body == [("#fetch", ("file", "'http://ex'", False, [], None, None))]


def test_fetch_async_directive_parsed():
    tokens = tokenize("{{#fetch async file from 'http://ex'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'", True, [], None, None))]


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


def test_fetch_header_directive_parsed():
    tokens = tokenize("{{#fetch file from 'http://ex' header=:hdr}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'", False, [":hdr"], None, None))]


def test_fetch_header_directive_dependencies():
    tokens = tokenize("{{#fetch dst from :url header=:hdr}}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"url", "hdr"}


def test_fetch_multiple_headers_parsed():
    tokens = tokenize("{{#fetch file from 'http://ex' header=:h1 header=:h2}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [
        ("#fetch", ("file", "'http://ex'", False, [":h1", ":h2"], None, None))
    ]


def test_fetch_body_directive_dependencies():
    tokens = tokenize("{{#fetch dst from :url body=:data}}")
    ast = build_ast(tokens, dialect="sqlite")
    deps = ast_param_dependencies(ast)
    assert deps == {"url", "data"}


def test_fetch_method_directive_parsed():
    tokens = tokenize("{{#fetch file from 'http://ex' method='POST'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'", False, [], "'POST'", None))]


def test_fetch_body_directive_parsed():
    tokens = tokenize("{{#fetch file from 'http://ex' body='hi'}}")
    body, _ = build_ast(tokens, dialect="sqlite")
    assert body == [("#fetch", ("file", "'http://ex'", False, [], None, "'hi'"))]


def test_fetch_directive_render():
    seen = []

    def fetch(url: str, headers=None, method="GET", body=None, **kwargs):
        seen.append((url, method))
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
    assert seen == [("http://x", "GET")]


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
            "{{#fetch d from 'http://127.0.0.1:'||:port}}{{d__status_code}} {{d__body}}",
        )
        out = r.render("/m", {"port": port}, reactive=False).body.strip()
        assert out == "200 hi"
    finally:
        server.shutdown()
        t.join()


def test_fetch_directive_custom_method():
    import http.server, threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = b"post"
            self.send_response(201)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            body = b"nope"
            self.send_response(405)
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
            "{{#fetch d from 'http://127.0.0.1:'||:port method='POST'}}{{d__status_code}} {{d__body}}",
        )
        out = r.render("/m", {"port": port}, reactive=False).body.strip()
        assert out == "201 post"
    finally:
        server.shutdown()
        t.join()


def test_fetch_commits_before_call(tmp_path):
    db_file = tmp_path / "db.sqlite"

    def fetch(_url: str, headers=None, method="GET", body=None, **kwargs):
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


def test_fetch_header_directive_render():
    seen = []

    def fetch(url: str, headers=None, method="GET", body=None, **kwargs):
        seen.append((url, headers, method))
        return {"a": "1"}

    from pageql import pageql as pql_mod
    old_fetch = pql_mod.fetch_sync
    pql_mod.fetch_sync = fetch
    try:
        r = PageQL(":memory:")
        r.load_module("m", "{{#fetch data from 'http://x' header=:hdr}}{{data__a}}")
        out = r.render("/m", {"hdr": "X: v"}, reactive=False).body
    finally:
        pql_mod.fetch_sync = old_fetch
    assert out.strip() == "1"
    assert seen == [("http://x", {"X": "v"}, "GET")]


def test_fetch_multiple_headers_render():
    seen = []

    def fetch(url: str, headers=None, method="GET", body=None, **kwargs):
        seen.append(headers)
        return {"a": "1"}

    from pageql import pageql as pql_mod
    old_fetch = pql_mod.fetch_sync
    pql_mod.fetch_sync = fetch
    try:
        r = PageQL(":memory:")
        r.load_module(
            "m",
            "{{#fetch data from 'http://x' header=:h1 header=:h2}}{{data__a}}",
        )
        out = r.render("/m", {"h1": "X: v1", "h2": "Y: v2"}, reactive=False).body
    finally:
        pql_mod.fetch_sync = old_fetch
    assert out.strip() == "1"
    assert seen == [{"X": "v1", "Y": "v2"}]


def test_fetch_body_directive_render():
    seen = []

    def fetch(url: str, headers=None, method="GET", body=None, **kwargs):
        seen.append((url, body))
        return {"a": "1"}

    from pageql import pageql as pql_mod
    old_fetch = pql_mod.fetch_sync
    pql_mod.fetch_sync = fetch
    try:
        r = PageQL(":memory:")
        r.load_module("m", "{{#fetch data from 'http://x' body='hi'}}{{data__a}}")
        out = r.render("/m", reactive=False).body
    finally:
        pql_mod.fetch_sync = old_fetch
    assert out.strip() == "1"
    assert seen == [("http://x", b"hi")]


def test_fetch_directive_handles_http_error():
    import http.server, threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"nope"
            self.send_response(400)
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
            "{{#fetch d from 'http://127.0.0.1:'||:port}}{{d__status_code}}",
        )
        out = r.render("/m", {"port": port}, reactive=False).body.strip()
        assert out == "400"
    finally:
        server.shutdown()
        t.join()




def test_fetch_directive_relative_url():
    import http.server, threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"ok"
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
        r.load_module("m", "{{#fetch d from '/healthz'}}{{d__body}}")
        out = r.render(
            "/m",
            {"headers": {"host": f"127.0.0.1:{port}"}, "path": "/m"},
            reactive=False,
        ).body.strip()
        assert out == "ok"
    finally:
        server.shutdown()
        t.join()
