import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

from pageql.pageql import parse_param_attrs


def test_single_double_and_unquoted_values():
    attrs = parse_param_attrs("a='one' b=two c=\"three\"")
    assert attrs == {"a": "one", "b": "two", "c": "three"}


def test_boolean_flags():
    assert parse_param_attrs("flag") == {"flag": True}
