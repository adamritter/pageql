import sys
from pathlib import Path
import types
import json
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL


def _final_text(body: str) -> str:
    prefix, rest = body.split("<script>pstart(0)</script>")
    inner, rest_after = rest.split("<script>pend(0)</script>", 1)
    value = inner
    for match in re.findall(r"<script>pset\(0,(.*?)\)</script>", rest_after):
        value = json.loads(match)
    return prefix + value


def test_reactive_set_variable_simple():
    snippet = (
        "{{#create table vars(val TEXT)}}"
        "{{#insert into vars(val) values ('ww')}}"
        "{{#reactive on}}"
        "{{#set a (select val from vars)}}"
        "hello {{a}}"
        "{{#update vars set val = 'world'}}"
    )
    r = PageQL(":memory:")
    r.load_module("react", snippet)
    result = r.render("/react")
    assert _final_text(result.body) == "hello world"
