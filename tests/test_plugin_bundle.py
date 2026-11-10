from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ui_exposes_one_click_game_installer():
    html = _text(ROOT / "static" / "index.html")
    ui = _text(ROOT / "entries" / "ui.py")

    assert 'id="gameInstallPath"' in html
    assert 'id="btnDetectGame"' in html
    assert 'id="btnInstallGame"' in html
    assert "pbz_installer_status" in html
    assert "pbz_install_game_mod" in html
    assert 'id="pbz_installer_status"' in ui
    assert 'id="pbz_install_game_mod"' in ui


def test_ui_guide_is_short_and_user_facing():
    config = tomllib.loads(_text(ROOT / "plugin.toml"))
    guide_config = config["plugin"]["ui"]["guide"][0]
    guide = ROOT / guide_config["entry"]
    text = _text(guide)

    assert guide_config["entry"] == "docs/ui/guide.md"
    assert guide.is_file()
    assert len(text) < 2200
    assert "快速开始" in text and "常见问题" in text
    assert "Assembly-CSharp" not in text
    assert "备份目录" not in text
    assert "权限清单" not in text


def test_user_docs_stay_short_and_have_no_changelog():
    readme = _text(ROOT / "README.md")

    assert len(readme) < 6000
    assert "## 安装" in readme and "## 常见问题" in readme
    assert not (ROOT / "docs" / "CHANGELOG.md").exists()


def test_no_separate_package_builder_or_plugin_archive():
    assert not (ROOT / "scripts").exists()
    assert not (ROOT / "game_bundle" / "install.ps1").exists()
    assert not (ROOT / "dist" / "neko_pbz_plugin_v0.0.3.zip").exists()


def test_installer_uses_discovery_instead_of_hardcoded_drive():
    source = _text(ROOT / "core" / "game_installer.py")

    assert "libraryfolders.vdf" in source
    assert "Win32_Process" not in source
    assert "GetLogicalDrives" in source
    assert "configured_root" in source
    assert '"E:\\\\"' not in source
    assert '"D:\\\\"' not in source


def test_runtime_manifest_is_pinned_and_market_package_excludes_binaries():
    manifest = json.loads(
        _text(ROOT / "game_bundle" / "runtime-manifest.json")
    )
    project = tomllib.loads(_text(ROOT / "pyproject.toml"))

    assert manifest["url"].startswith("https://")
    assert re.fullmatch(r"[0-9A-F]{64}", manifest["sha256"])
    assert 0 < manifest["size"] < 64 * 1024 * 1024
    assert "game_bundle/runtime" in project["tool"]["neko"]["build"]["exclude_dirs"]


def test_game_assets_and_tools_use_one_bundle_root():
    assert (ROOT / "game_bundle" / "mod" / "js").is_dir()
    assert (ROOT / "game_bundle" / "mod" / "lua").is_dir()
    assert (ROOT / "game_bundle" / "runtime-manifest.json").is_file()
    assert (ROOT / "game_bundle" / "tools" / "deploy.ps1").is_file()
    assert (
        ROOT / "game_bundle" / "tools" / "sync_vendor_ue4ss.ps1"
    ).is_file()
    assert not (ROOT / "installer").exists()
    assert not (ROOT / "mod").exists()
