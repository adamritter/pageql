import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.modules.setdefault("watchfiles", types.ModuleType("watchfiles"))
sys.modules["watchfiles"].awatch = lambda *args, **kwargs: None

import warnings

warnings.filterwarnings(
    "ignore",
    message=r"websockets\.server\.WebSocketServerProtocol is deprecated",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message="remove second argument of ws_handler",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"This process .* fork\(\) may lead to deadlocks in the child.",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"websockets\.legacy is deprecated;.*",
    category=DeprecationWarning,
)
