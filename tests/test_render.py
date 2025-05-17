import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import types
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

from pageql.pageql import PageQL


def test_render_nonexistent_returns_404():
    r = PageQL(":memory:")
    result = r.render("/nonexistent")
    assert result.status_code == 404


def test_reactive_toggle():
    r = PageQL(":memory:")
    r.load_module("reactive", "{{reactive}} {{#reactive on}}{{reactive}}{{#reactive off}}{{reactive}}")
    result = r.render("/reactive")
    assert result.body.strip() == "False True False"


if __name__ == "__main__":
    test_render_nonexistent_returns_404()
