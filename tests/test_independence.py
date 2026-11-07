"""插件/Mod 必须运行时自包含：其他插件只可参考，不可 import。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OTHER_PLUGINS = ("neko_arcade", "neko_terraria", "neko_danmaku",
                 "neko_kittytrain", "neko_pawpilot")


def test_python_has_no_cross_plugin_imports():
    files = [ROOT / "__init__.py"]
    for folder in ("core", "entries", "adapters"):
        files.extend((ROOT / folder).glob("*.py"))
    bad = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name in OTHER_PLUGINS:
            if re.search(rf"(?m)^\s*(from|import)\s+.*\b{name}\b", text):
                bad.append(f"{path.name} imports {name}")
            if f"plugin.plugins.{name}" in text and "import" in text:
                bad.append(f"{path.name} references plugin.plugins.{name}")
    assert not bad, "运行时跨插件依赖: " + "; ".join(bad)


def test_game_mod_requires_only_game_apis_and_local_files():
    allowed = {"ue", "puerts", "Library/TsHelper"}
    bad = []
    for path in (ROOT / "mod" / "pbz-neko-companion").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        for dep in re.findall(r"require\([\"']([^\"']+)[\"']\)", text):
            if dep in allowed or dep.startswith("./"):
                continue
            bad.append(f"{path.name}: {dep}")
    assert not bad, "游戏 Mod 依赖了非本地模块: " + ", ".join(bad)


def test_llm_client_is_vendored():
    """独立 LLM 客户端必须是本插件文件，而不是运行时 import 其他插件。"""
    vendor = ROOT / "adapters" / "llm_client.py"
    assert vendor.exists()
    text = vendor.read_text(encoding="utf-8")
    assert "class LLMClient" in text and "class LLMProvider" in text
