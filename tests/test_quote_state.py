import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")


from pageql.parser import quote_state

def test_quote_state():
    assert quote_state('hello') is None
    assert quote_state("'a'") is None
    assert quote_state("'a") == "'"
    assert quote_state('"a') == '"'
    # starting in quote
    assert quote_state('b"', '"') is None


