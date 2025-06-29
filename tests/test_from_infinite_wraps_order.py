import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.pageql import PageQL
from pageql.reactive import Order


def test_infinite_from_wraps_order_limit_100():
    page = """
    {{#create table items(id INTEGER)}}
    {{#insert into items(id) values (1)}}
    <div>
    {{#from items infinite}}
      {{id}}
    {{/from}}
    </div>
    """
    r = PageQL(":memory:")
    r.load_module("test", page)
    result = r.render("/test")
    ctx = result.context
    assert len(ctx.infinites) == 1
    order = list(ctx.infinites.values())[0]
    assert isinstance(order, Order)
    assert order.limit == 100

def test_infinite_from_readonly_is_wrapped():
    page = """
    <div>
    {{#from (SELECT 2 AS n UNION ALL SELECT 1 AS n) order by n limit 1 infinite}}
      {{n}}
    {{/from}}
    </div>
    """
    r = PageQL(":memory:")
    r.load_module("test_ro", page)
    result = r.render("/test_ro")
    ctx = result.context
    assert len(ctx.infinites) == 1
    order = list(ctx.infinites.values())[0]
    assert isinstance(order, Order)
    assert order.limit == 100
    assert order.conn is None
