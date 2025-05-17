import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL
from pageql.reactive import Signal, DerivedSignal


def test_render_nonexistent_returns_404():
    r = PageQL(":memory:")
    result = r.render("/nonexistent")
    assert result.status_code == 404


def test_reactive_toggle():
    r = PageQL(":memory:")
    r.load_module("reactive", "{{reactive}} {{#reactive on}}{{reactive}} {{#reactive off}}{{reactive}}")
    result = r.render("/reactive")
    assert result.body.strip() == "False True False"


def test_set_signal_reactive_on():
    r = PageQL(":memory:")
    r.load_module("sig", "{{#reactive on}}{{#set foo 42}}")
    params = {"foo": Signal(0)}
    r.render("/sig", params)
    assert isinstance(params["foo"], DerivedSignal)
    assert params["foo"].value == 42


def test_set_creates_derived_signal_with_dependencies():
    r = PageQL(":memory:")
    r.load_module("dep", "{{#reactive on}}{{#set result :val + 1}}")
    params = {"val": Signal(1)}
    r.render("/dep", params)
    result_sig = params["result"]
    assert isinstance(result_sig, DerivedSignal)
    events = []
    result_sig.listeners.append(events.append)
    params["val"].set(2)
    assert result_sig.value == 3
    assert events[-1] == 3


if __name__ == "__main__":
    test_render_nonexistent_returns_404()
