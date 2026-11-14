from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manifest_exists() -> None:
    manifest = ROOT / "plugin.toml"
    assert manifest.is_file()
    text = manifest.read_text(encoding="utf-8")
    assert 'id = "neko_pbz"' in text
    assert 'entry = "plugin.plugins.neko_pbz:NekoPbzPlugin"' in text
    assert "[plugin_runtime]" not in text
    runtime_example = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    assert "[plugin_runtime]" in runtime_example


def test_release_version_and_package_metadata_match() -> None:
    plugin = tomllib.loads((ROOT / "plugin.toml").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert plugin["plugin"]["version"] == "0.0.3"
    assert project["project"]["version"] == plugin["plugin"]["version"]


def test_ui_guide_and_game_bundle_exist() -> None:
    plugin = tomllib.loads((ROOT / "plugin.toml").read_text(encoding="utf-8"))

    for panel in plugin["plugin"]["ui"]["panel"]:
        assert (ROOT / panel["entry"]).is_file()
    for guide in plugin["plugin"]["ui"]["guide"]:
        assert (ROOT / guide["entry"]).is_file()
    assert (
        ROOT / "game_bundle" / "mod" / "js" / "pbz-neko-companion" / "main.js"
    ).is_file()
    assert (
        ROOT / "game_bundle" / "runtime-manifest.json"
    ).is_file()
