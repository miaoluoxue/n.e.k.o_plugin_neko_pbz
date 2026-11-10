from __future__ import annotations

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


def test_no_separate_package_builder_or_plugin_archive():
    assert not (ROOT / "scripts" / "build_oneclick.ps1").exists()
    assert not (ROOT / "installer" / "install.ps1").exists()
    assert not (ROOT / "dist" / "neko_pbz_plugin_v0.2.0.zip").exists()


def test_installer_uses_discovery_instead_of_hardcoded_drive():
    source = _text(ROOT / "core" / "game_installer.py")

    assert "libraryfolders.vdf" in source
    assert "Win32_Process" not in source
    assert "GetLogicalDrives" in source
    assert "configured_root" in source
    assert '"E:\\\\"' not in source
    assert '"D:\\\\"' not in source


def test_vendor_snapshot_contains_only_required_runtime():
    vendor = ROOT / "installer" / "vendor" / "ue4ss"
    for relative in (
        "dwmapi.dll",
        "version.dll",
        "ue4ss/UE4SS.dll",
        "ue4ss/MemberVariableLayout.ini",
        "ue4ss/UE4SS_Signatures/GUObjectArray.lua",
        "ue4ss/Mods/Keybinds/Scripts/main.lua",
        "ue4ss/Mods/BPModLoaderMod/Scripts/main.lua",
        "ue4ss/Mods/mods.txt",
        "vendor.json",
    ):
        assert (vendor / relative).is_file(), relative

    copied_mod_names = {
        path.name for path in (vendor / "ue4ss" / "Mods").iterdir()
        if path.is_dir()
    }
    assert "PBZQuestGuide" not in copied_mod_names
    assert "PBZGuideHotkeys" not in copied_mod_names
    assert "PBZNekoCompanion" not in copied_mod_names
