import sys, types

# Stub watchfiles so importing pageql doesn't fail
if 'watchfiles' not in sys.modules:
    sys.modules['watchfiles'] = types.ModuleType('watchfiles')
    sys.modules['watchfiles'].awatch = None

sys.path.insert(0, 'src')
from pageql.pageql import parse_param_attrs


def test_single_quotes():
    result = parse_param_attrs("name='John Doe'")
    assert result == {'name': 'John Doe'}


def test_double_quotes():
    result = parse_param_attrs('title="Hello World"')
    assert result == {'title': 'Hello World'}


def test_unquoted_value():
    result = parse_param_attrs('count=5')
    assert result == {'count': '5'}


def test_boolean_flag():
    result = parse_param_attrs('secure')
    assert result == {'secure': True}


if __name__ == '__main__':
    test_single_quotes()
    test_double_quotes()
    test_unquoted_value()
    test_boolean_flag()
