import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.pageql import PageQL, _row_hash


def test_infinite_from_logs_mid_after_pend():
    r = PageQL(":memory:")
    r.load_module("m", "{{#from (select 1 as id) infinite}}{{id}}{{#endfrom}}")
    result = r.render("/m")
    expected = (
        "<script>pstart(0)</script>"
        "<script>pstart(1)</script>1<script>pend(1)</script>\n"
        "<script>pend(0)</script><script>maybe_load_more(document.body, 0)</script>"
    )
    assert result.body == expected
