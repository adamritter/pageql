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
