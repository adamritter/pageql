import sys
sys.path.insert(0, "src")

from pageql.database import parse_param_attrs


def test_single_double_and_unquoted_values():
    attrs = parse_param_attrs("a='one' b=two c=\"three\"")
    assert attrs == {"a": "one", "b": "two", "c": "three"}


def test_boolean_flags():
    assert parse_param_attrs("flag") == {"flag": True}
