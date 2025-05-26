import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))

async def _awatch_stub(*args, **kwargs):
    if False:
        yield None

sys.modules["watchfiles"].awatch = _awatch_stub
