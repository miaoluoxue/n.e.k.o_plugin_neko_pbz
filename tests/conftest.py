"""本地独立运行时建立 plugin.plugins.neko_pbz 包链。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if "plugin.plugins.neko_pbz" not in sys.modules:
    plugin = types.ModuleType("plugin")
    plugin.__path__ = []
    plugins = types.ModuleType("plugin.plugins")
    plugins.__path__ = []
    pkg = types.ModuleType("plugin.plugins.neko_pbz")
    pkg.__path__ = [str(ROOT)]
    sys.modules["plugin"] = plugin
    sys.modules["plugin.plugins"] = plugins
    sys.modules["plugin.plugins.neko_pbz"] = pkg

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
