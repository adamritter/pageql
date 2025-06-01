import sys, types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *a, **k: None
sys.path.insert(0, "src")

import pytest
from pageql.pageql import PageQL


def test_param_float_validation():
    r = PageQL(":memory:")
    r.load_module("m", "{{#param val type=float min=1.5 max=3.5}}{{val}}")
    result = r.render("/m", {"val": "2.0"}, reactive=False)
    assert result.body == "2.0"
    with pytest.raises(ValueError) as exc:
        r.render("/m", {"val": "1"}, reactive=False)
    assert "less than min 1.5" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        r.render("/m", {"val": "4"}, reactive=False)
    assert "greater than max 3.5" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        r.render("/m", {"val": "abc"}, reactive=False)
    assert "failed type/validation 'float'" in str(exc.value)


def test_missing_param_error():
    r = PageQL(":memory:")
    r.load_module("m", "{{#let session :non_existent}}")
    with pytest.raises(ValueError) as exc:
        r.render("/m", reactive=False)
    msg = str(exc.value).lower()
    assert "missing parameter 'non_existent'" in msg
    assert "available parameters" in msg


def test_param_nested_name():
    r = PageQL(":memory:")
    r.load_module("m", "{{#param cookies.session optional}}{{cookies__session}}")
    result = r.render("/m", {"cookies": {"session": "abc"}}, reactive=False)
    assert result.body == "abc"
