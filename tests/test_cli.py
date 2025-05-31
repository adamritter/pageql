import sys
from pathlib import Path
import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

import pageql.cli as cli

def test_cli_fallback_url(monkeypatch, tmp_path):
    created = {}

    class DummyApp:
        def __init__(
            self,
            db_file,
            templates_dir,
            create_db=False,
            should_reload=True,
            quiet=False,
            fallback_app=None,
            fallback_url=None,
            csrf_protect=True,
        ):
            created["db"] = db_file
            created["tpl"] = templates_dir
            created["fallback_url"] = fallback_url

    monkeypatch.setattr(cli, "PageQLApp", DummyApp)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: None)

    argv = [
        "pageql",
        "test.db",
        str(tmp_path),
        "--fallback-url",
        "http://example.com",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert created["fallback_url"] == "http://example.com"

