from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from plugin.plugins.neko_pbz.core import game_installer as game_installer_module
from plugin.plugins.neko_pbz.core.game_installer import GameInstaller


def _make_plugin(root: Path, *, with_runtime: bool = True) -> None:
    runtime = root / "game_bundle" / "runtime"
    if with_runtime:
        (runtime / "ue4ss" / "Mods").mkdir(parents=True)
        (runtime / "dwmapi.dll").write_bytes(b"ue4ss-proxy")
        (runtime / "version.dll").write_bytes(b"pbz-loader")
        (runtime / "ue4ss" / "UE4SS.dll").write_bytes(b"bundled-ue4ss")
        (runtime / "ue4ss" / "Mods" / "mods.txt").write_text(
            "Keybinds : 1\n", encoding="utf-8")

    manifest = root / "game_bundle" / "runtime-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "schema": 1,
        "runtime": "test runtime",
        "url": "https://example.invalid/runtime.zip",
        "sha256": "0" * 64,
        "size": 1,
    }), encoding="utf-8")

    js = root / "game_bundle" / "mod" / "js" / "pbz-neko-companion"
    js.mkdir(parents=True)
    (js / "main.js").write_text("game mod", encoding="utf-8")
    (js / "game_api.js").write_text("live state", encoding="utf-8")

    lua = root / "game_bundle" / "mod" / "lua" / "PBZNekoCompanion"
    (lua / "Scripts").mkdir(parents=True)
    (lua / "Scripts" / "main.lua").write_text("lua mod", encoding="utf-8")
    (lua / "enabled.txt").write_text("1", encoding="ascii")


def _make_game(root: Path, *, with_ue4ss: bool) -> None:
    (root / "platform" / "steam").mkdir(parents=True)
    (root / "platform" / "steam" / "PBZ.exe").write_bytes(b"game")
    loader = root / "ProjectPBZ" / "Content" / "JavaScript" / "PBZModLoader"
    loader.mkdir(parents=True)
    (loader / "generated-config.js").write_text(
        "'use strict';\nmodule.exports = {\"version\":1,\"mods\":["
        "{\"id\":\"other\",\"enabled\":true,"
        "\"entry\":\"mods/other/main.js\"}]};\n",
        encoding="utf-8",
    )
    (loader / "generated-mods" / "other").mkdir(parents=True)
    (loader / "generated-mods" / "other" / "main.js").write_text(
        "keep", encoding="utf-8")
    persistent = root / "ProjectPBZ" / "PBZModLoader"
    persistent.mkdir(parents=True, exist_ok=True)
    (persistent / "mods.ini").write_text(
        "[Loader]\nEnabled=1\nVersion=1\n\n[Mods]\nother=1\n",
        encoding="utf-8",
    )

    if with_ue4ss:
        mods = root / "platform" / "steam" / "ue4ss" / "Mods"
        mods.mkdir(parents=True)
        (mods / "mods.txt").write_text("OtherMod : 1\n", encoding="utf-8")
        other = mods / "OtherMod"
        other.mkdir()
        (other / "sentinel.txt").write_text("keep", encoding="utf-8")
        (root / "platform" / "steam" / "ue4ss" / "UE4SS.dll").write_bytes(
            b"existing-ue4ss")


def test_detection_normalizes_subdirectory_and_never_hardcodes_drives(tmp_path):
    plugin = tmp_path / "plugin"
    _make_plugin(plugin)
    game = tmp_path / "library" / "steamapps" / "common" / "PBZ"
    _make_game(game, with_ue4ss=True)
    installer = GameInstaller(
        plugin, tmp_path / "data", bridge_root=str(tmp_path / "bridge"))

    assert installer.normalize_root(str(game / "platform" / "steam")) == game
    status = installer.status(str(game))
    assert status["ok"] is True
    assert status["game_root"] == str(game.resolve())
    assert status["ue4ss_present"] is True
    source = Path(__file__).resolve().parent.parent / "core" / "game_installer.py"
    text = source.read_text(encoding="utf-8")
    assert '"E:\\\\"' not in text and '"D:\\\\"' not in text


def test_install_preserves_existing_ue4ss_and_other_mods(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(GameInstaller, "game_running", staticmethod(lambda: False))
    plugin = tmp_path / "plugin"
    _make_plugin(plugin)
    game = tmp_path / "game"
    _make_game(game, with_ue4ss=True)

    result = GameInstaller(
        plugin, tmp_path / "data", bridge_root=str(tmp_path / "bridge"),
    ).install(
        str(game / "platform" / "steam"))

    assert result["ok"] is True
    assert result["ue4ss_preserved"] is True
    assert (
        game / "platform" / "steam" / "ue4ss" / "UE4SS.dll"
    ).read_bytes() == b"existing-ue4ss"
    assert (
        game / "platform" / "steam" / "ue4ss" / "Mods" /
        "OtherMod" / "sentinel.txt"
    ).read_text(encoding="utf-8") == "keep"
    config = (
        game / "ProjectPBZ" / "Content" / "JavaScript" / "PBZModLoader" /
        "generated-config.js"
    ).read_text(encoding="utf-8")
    assert '"id":"other"' in config
    assert '"id":"pbz-neko-companion"' in config
    mods = (
        game / "platform" / "steam" / "ue4ss" / "Mods" / "mods.txt"
    ).read_text(encoding="utf-8")
    assert "OtherMod : 1" in mods
    assert "PBZNekoCompanion : 1" in mods
    assert (
        game / "ProjectPBZ" / "Content" / "JavaScript" / "PBZModLoader" /
        "generated-mods" / "pbz-neko-companion" / "main.js"
    ).is_file()
    assert (
        game / "ProjectPBZ" / "PBZModLoader" / "mods" /
        "pbz-neko-companion" / "main.js"
    ).is_file()
    mods_ini = (
        game / "ProjectPBZ" / "PBZModLoader" / "mods.ini"
    ).read_text(encoding="utf-8")
    assert "other=1" in mods_ini
    assert "pbz-neko-companion=1" in mods_ini
    status = GameInstaller(
        plugin, tmp_path / "data", bridge_root=str(tmp_path / "bridge"),
    ).status(str(game))
    assert status["mod_installed"] is True
    assert status["mod_enabled"] is True
    assert status["generated_mod_present"] is True


def test_install_adds_local_runtime_only_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(GameInstaller, "game_running", staticmethod(lambda: False))
    plugin = tmp_path / "plugin"
    _make_plugin(plugin)
    game = tmp_path / "game"
    _make_game(game, with_ue4ss=False)

    result = GameInstaller(
        plugin, tmp_path / "data", bridge_root=str(tmp_path / "bridge"),
    ).install(str(game))

    assert result["ue4ss_preserved"] is False
    assert (
        game / "platform" / "steam" / "ue4ss" / "UE4SS.dll"
    ).read_bytes() == b"bundled-ue4ss"
    assert (game / "platform" / "steam" / "dwmapi.dll").is_file()
    assert (game / "platform" / "steam" / "version.dll").is_file()
    state = game / "_neko_pbz_backup"
    states = list(state.rglob("install-state.json"))
    assert states
    payload = json.loads(states[0].read_text(encoding="utf-8"))
    assert payload["game_root"] == str(game.resolve())


def test_generated_cache_reset_keeps_source_mod_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(GameInstaller, "game_running", staticmethod(lambda: False))
    plugin = tmp_path / "plugin"
    _make_plugin(plugin)
    game = tmp_path / "game"
    _make_game(game, with_ue4ss=True)
    installer = GameInstaller(
        plugin, tmp_path / "data", bridge_root=str(tmp_path / "bridge"),
    )
    assert installer.install(str(game))["ok"] is True

    loader = game / "ProjectPBZ" / "Content" / "JavaScript" / "PBZModLoader"
    (loader / "generated-config.js").write_text(
        "'use strict';\nmodule.exports = {\"version\":1,\"mods\":[]};\n",
        encoding="utf-8",
    )
    shutil.rmtree(loader / "generated-mods" / "pbz-neko-companion")

    status = installer.status(str(game))
    assert status["generated_mod_present"] is False
    assert status["mod_installed"] is True
    assert status["mod_enabled"] is True


def test_install_downloads_and_verifies_runtime_when_package_has_no_binary(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(GameInstaller, "game_running", staticmethod(lambda: False))
    plugin = tmp_path / "plugin"
    _make_plugin(plugin, with_runtime=False)
    game = tmp_path / "game"
    _make_game(game, with_ue4ss=False)

    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("dwmapi.dll", b"downloaded-proxy")
        bundle.writestr("version.dll", b"downloaded-loader")
        bundle.writestr("ue4ss/UE4SS.dll", b"downloaded-ue4ss")
        bundle.writestr("ue4ss/Mods/mods.txt", "Keybinds : 1\n")

    digest = hashlib.sha256(archive.read_bytes()).hexdigest().upper()
    manifest = plugin / "game_bundle" / "runtime-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 1,
        "runtime": "test runtime",
        "url": "https://example.invalid/runtime.zip",
        "sha256": digest,
        "size": archive.stat().st_size,
    }), encoding="utf-8")

    def fake_download(_url: str, destination: Path) -> None:
        shutil.copy2(archive, destination)

    monkeypatch.setattr(
        game_installer_module, "_download_runtime_archive", fake_download
    )
    result = GameInstaller(
        plugin, tmp_path / "data", bridge_root=str(tmp_path / "bridge"),
    ).install(str(game))

    assert result["ue4ss_preserved"] is False
    assert (
        game / "platform" / "steam" / "ue4ss" / "UE4SS.dll"
    ).read_bytes() == b"downloaded-ue4ss"
    assert (
        game / "platform" / "steam" / "dwmapi.dll"
    ).read_bytes() == b"downloaded-proxy"
