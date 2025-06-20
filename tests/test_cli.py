import sys
from pathlib import Path
import types
import pytest

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
            http_disconnect_cleanup_timeout=10.0,
            static_html=False,
        ):
            created["db"] = db_file
            created["tpl"] = templates_dir
            created["fallback_url"] = fallback_url

    monkeypatch.setattr(cli, "PageQLApp", DummyApp)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: None)

    argv = [
        "pageql",
        str(tmp_path),
        "test.db",
        "--fallback-url",
        "http://example.com",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert created["fallback_url"] == "http://example.com"


def test_cli_test_command(monkeypatch, tmp_path, capsys):
    (tmp_path / "t.pageql").write_text(
        "{{#test a}}{{#create table t(x int)}}{{#insert into t values (1)}}{{count(*) from t}}{{/test}}"
    )
    argv = ["pageql", str(tmp_path), "db.sqlite", "--test"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "1/1 tests passed" in out


def test_cli_http_disconnect_timeout(monkeypatch, tmp_path):
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
            http_disconnect_cleanup_timeout=10.0,
            static_html=False,
        ):
            created["timeout"] = http_disconnect_cleanup_timeout

    monkeypatch.setattr(cli, "PageQLApp", DummyApp)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: None)

    argv = [
        "pageql",
        str(tmp_path),
        "db",
        "--http-disconnect-cleanup-timeout",
        "0.5",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert created["timeout"] == 0.5


def test_cli_static_html(monkeypatch, tmp_path):
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
            http_disconnect_cleanup_timeout=10.0,
            static_html=False,
        ):
            created["static_html"] = static_html

    monkeypatch.setattr(cli, "PageQLApp", DummyApp)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: None)

    argv = [
        "pageql",
        str(tmp_path),
        "db",
        "--static-html",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()
    assert created["static_html"] is True


