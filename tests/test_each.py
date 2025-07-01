import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.pageql import PageQL
from pageql.parser import tokenize, build_ast, ast_param_dependencies
from pageql.pageqlapp import PageQLApp
import asyncio
from pathlib import Path


def test_each_basic():
    r = PageQL(":memory:")
    r.load_module("m", "{{#each items}}[{{items}}]{{#endeach}}")
    params = {
        "items__count": 3,
        "items__0": "a",
        "items__1": "b",
        "items__2": "c",
    }
    result = r.render("/m", params, reactive=False)
    assert result.body == "[a]\n[b]\n[c]\n"


def test_each_ast_dependencies():
    snippet = "{{#each nums}}{{#endeach}}"
    tokens = tokenize(snippet)
    ast = build_ast(tokens)
    deps = ast_param_dependencies(ast)
    assert deps == {"nums__count"}


def test_each_array_in_params(tmp_path):
    (tmp_path / "loop.pageql").write_text("{{#each items}}{{items}}{{#endeach}}", encoding="utf-8")

    async def run():
        app = PageQLApp(":memory:", tmp_path, create_db=True, should_reload=False)
        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "http.request"}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/loop",
            "headers": [],
            "query_string": b"items=a&items=b&items=c",
        }

        await app.pageql_handler(scope, receive, send)
        return sent

    messages = asyncio.run(run())
    body = next(m for m in messages if m["type"] == "http.response.body")[
        "body"
    ].decode()
    assert "pstart(0)</script>a<script" in body
    assert "pstart(1)</script>b<script" in body
    assert "pstart(2)</script>c<script" in body
