import pageql
import tomllib
from pathlib import Path


def test_version_matches_pyproject():
    root = Path(__file__).resolve().parents[1]
    pyproject_file = root / "pyproject.toml"
    data = tomllib.loads(pyproject_file.read_text())
    assert pageql.__version__ == data["project"]["version"]
