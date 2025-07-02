import sys
from pathlib import Path
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pageql


def test_version_matches_pyproject():
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        pyproject_version = tomllib.load(f)["project"]["version"]
    assert pageql.__version__ == pyproject_version
