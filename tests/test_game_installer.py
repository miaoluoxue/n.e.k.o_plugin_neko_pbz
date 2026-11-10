from __future__ import annotations

import json
from pathlib import Path

from plugin.plugins.neko_pbz.core.game_installer import GameInstaller


def _make_plugin(root: Path) -> None:
    vendor = root / "installer" / "vendor" / "ue4ss"
    (vendor / "ue4ss" / "Mods").mkdir(parents=True)
    (vendor / "dwmapi.dll").write_bytes(b"ue4ss-proxy")
    (vendor / "version.dll").write_bytes(b"pbz-loader")
    (vendor / "ue4ss" / "UE4SS.dll").write_bytes(b"bundled-ue4ss")
    (vendor / "ue4ss" / "Mods" / "mods.txt").write_text(
        "Keybinds : 1\n", encoding="utf-8")

    js = root / "mod" / "pbz-neko-companion"
    js.mkdir(parents=True)
    (js / "main.js").write_text("game mod", encoding="utf-8")
    (js / "game_api.js").write_text("live state", encoding="utf-8")

    lua = root / "mod" / "lua" / "PBZNekoCompanion"
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


def test_install_adds_bundled_ue4ss_only_when_missing(tmp_path, monkeypatch):
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
