from pageql.pageql import _normalize_param_name

def test_normalize_param_name():
    assert _normalize_param_name(':a.b') == 'a__b'
    assert _normalize_param_name('foo') == 'foo'
