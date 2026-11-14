from __future__ import annotations

from plugin.plugins.neko_pbz.core import config as config_module
from plugin.plugins.neko_pbz.core.config import ConfigStore


def test_llm_settings_roundtrip(tmp_path):
    store = ConfigStore(tmp_path)
    cfg = store.save({
        "llm_enabled": True,
        "llm_provider": "openai_compatible",
        "llm_model": "deepseek-chat",
        "llm_api_key": "sk-test",
        "llm_base_url": "https://api.deepseek.com",
        "llm_timeout": 18,
        "llm_max_calls_per_minute": 8,
    })
    assert cfg["llm_enabled"] is True
    loaded = store.load()
    assert loaded["llm_model"] == "deepseek-chat"
    assert loaded["llm_api_key"] == "sk-test"
    assert loaded["llm_base_url"] == "https://api.deepseek.com"
    assert loaded["llm_timeout"] == 18
    assert loaded["llm_max_calls_per_minute"] == 8
    assert (tmp_path / "config" / "general.json").exists()
    assert (tmp_path / "config" / "llm.json").exists()
    assert (tmp_path / "config" / "ui.json").exists()
    assert not (tmp_path / "config" / "user.json").exists()
    raw = (tmp_path / "config" / "llm.json").read_text(encoding="utf-8")
    assert "sk-test" not in raw
    assert "llm_api_key_enc" in raw


def test_empty_llm_key_is_removed(tmp_path):
    store = ConfigStore(tmp_path)
    store.save({"llm_api_key": "sk-secret"})
    cfg = store.save({"llm_api_key": ""})
    assert cfg["llm_api_key"] == ""
    assert store.load()["llm_api_key"] == ""


def test_bridge_prefers_latest_game_state_path(tmp_path, monkeypatch):
    configured = tmp_path / "wrong" / "NekoBridge"
    configured.mkdir(parents=True)
    local_app = tmp_path / "LocalAppData"
    active = local_app / "ProjectPBZ" / "Saved" / "NekoBridge"
    state = active / "state" / "New_CSV.csv"
    state.parent.mkdir(parents=True)
    state.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app))
    monkeypatch.setattr(config_module, "_BRIDGE_CANDIDATES", ())
    monkeypatch.setattr(config_module, "_home_documents", lambda: ())
    assert config_module.resolve_bridge_dir(str(configured)) == active


def test_config_save_uses_writable_plugin_fallback(tmp_path, monkeypatch):
    local_app = tmp_path / "LocalAppData"
    local_app.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local_app))
    monkeypatch.setattr(config_module, "_BRIDGE_CANDIDATES", ())
    monkeypatch.setattr(config_module, "_home_documents", lambda: ())
    store = ConfigStore(tmp_path / "plugin-data")
    cfg = store.save({"voice_enabled": False})
    fallback = tmp_path / "plugin-data" / "bridge"
    assert cfg["bridge_dir"] == str(fallback)
    assert fallback.is_dir()
