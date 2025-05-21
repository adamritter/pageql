import types, sys
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None
sys.path.insert(0, "src")

import pytest
from pageql.parser import tokenize

def test_unmatched_braces():
    with pytest.raises(SyntaxError) as exc:
        tokenize(
            "something like {{#a\n{{#set active_count    COUNT(*) from todos WHERE completed = 0}}"
        )
    assert "mismatched {{ in token" in str(exc.value)
