from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from plugin.plugins.neko_pbz.core.service import PbzService


class _Conv:
    def __init__(self):
        self.text = ""
        self.ts = 0.0

    async def get(self, since_ts=0, max_count=50, timeout=2.0):
        if not self.text or self.ts <= since_ts:
            return []

        class Rec:
            timestamp = self.ts
            content = self.text
            turn_type = "proactive_reply"
            lanlan_name = ""

        return [Rec()]


class _Ctx:
    def __init__(self):
        self.bus = type("Bus", (), {"conversations": _Conv()})()
        self.lanlan_name = ""


class _Plugin:
    def __init__(self, root: Path):
        self.ctx = _Ctx()
        self.calls = []
        self.root = root

    def push_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"submitted": True}

    def data_path(self, *parts):
        return self.root.joinpath(*parts)


def test_low_hp_pushes_respond_then_writes_final_subtitle(tmp_path):
    plugin = _Plugin(tmp_path / "data")
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    cfg = {
        "bridge_dir": str(bridge), "poll_interval": 0.1,
        "state_stale_seconds": 30, "voice_enabled": True,
        "spoiler_level": 1, "proactive": True,
        "boss_advice_min": 1, "boss_advice_max": 3,
        "quiet_until": 0, "host_reply_timeout": 10,
        "event_log_limit": 20,
    }
    state = {
        "version": 1, "seq": 1, "ts": time.time(),
        "game": {"cutscene": False, "menu_open": False},
        "world": {"id": "XiGu", "name": "悲泣溪谷"},
        "player": {"name": "black", "hp_percent": 22, "in_combat": True,
                   "dead": False, "shachi": {"percent": 50},
                   "equipment": {"main_weapon": {"id": "Weapon_001", "name": "黑伤"},
                                 "phantom_edges": [], "accessories": []}},
        "enemies": [], "boss": None, "quests": [],
        "bell": {"near": False, "activated": False, "id": ""},
    }
    bridge.joinpath("state.json").write_text(json.dumps(state), encoding="utf-8")

    svc = PbzService(plugin, cfg, tmp_path / "data")

    async def run():
        await svc._tick()
        assert plugin.calls, "低血应触发一次 respond"
        assert plugin.calls[-1]["ai_behavior"] == "respond"
        conv = plugin.ctx.bus.conversations
        conv.text = "别怕，喵在这儿。"
        conv.ts = svc.speech.pending_ts + 0.01
        svc.speech.watcher.last_ts = svc.speech.pending_ts - 0.01
        await svc._poll_final()
        assert svc.bridge.read_reply()["text"] == "别怕，喵在这儿。"
        await svc.stop()

    asyncio.run(run())


def test_llm_priority_independent_then_host_fallback(tmp_path):
    plugin = _Plugin(tmp_path / "data")

    async def host_llm(prompt):
        return "宿主回复"

    setattr(plugin, "__call_llm", host_llm)
    base = {
        "bridge_dir": str(tmp_path / "bridge2"), "poll_interval": 0.1,
        "state_stale_seconds": 30, "voice_enabled": True,
        "spoiler_level": 1, "proactive": True,
        "boss_advice_min": 1, "boss_advice_max": 3,
        "quiet_until": 0, "host_reply_timeout": 10,
        "event_log_limit": 20,
        "llm_enabled": False, "llm_provider": "", "llm_model": "",
        "llm_api_key": "", "llm_base_url": "",
        "llm_timeout": 10, "llm_max_calls_per_minute": 5,
    }
    svc = PbzService(plugin, dict(base), tmp_path / "data")
    assert svc.llm_mode == "host"

    async def run():
        result = await svc.test_llm()
        assert result["ok"] is True
        assert result["output"] == "宿主回复"
        await svc.stop()

    asyncio.run(run())

    independent = dict(base)
    independent.update({
        "llm_enabled": True,
        "llm_provider": "openai_compatible",
        "llm_model": "deepseek-chat",
        "llm_api_key": "sk-test",
        "llm_base_url": "https://api.deepseek.com",
    })
    svc2 = PbzService(plugin, independent, tmp_path / "data2")
    assert svc2.llm_mode == "independent"
    asyncio.run(svc2.stop())


def test_assist_uses_current_quest_and_host_persona(tmp_path):
    plugin = _Plugin(tmp_path / "data")
    bridge = tmp_path / "bridge-assist"
    bridge.mkdir()
    cfg = {
        "bridge_dir": str(bridge), "poll_interval": 0.1,
        "state_stale_seconds": 30, "voice_enabled": True,
        "spoiler_level": 2, "proactive": True,
        "boss_advice_min": 1, "boss_advice_max": 3,
        "quiet_until": 0, "host_reply_timeout": 10,
        "event_log_limit": 20,
        "assist_enabled": True, "assist_cooldown": 0,
    }
    state = {
        "version": 1, "seq": 1, "ts": time.time(),
        "game": {"cutscene": False, "menu_open": False},
        "world": {"id": "FuJiZhiLin", "name": "血色森林"},
        "player": {"name": "black", "hp_percent": 88, "in_combat": False,
                   "dead": False, "shachi": {"percent": 64},
                   "equipment": {"main_weapon": {"id": "Weapon_001", "name": "黑伤"},
                                 "phantom_edges": [], "accessories": []}},
        "enemies": [], "boss": None,
        "quests": [{"id": "BaiShanMiWen", "name": "白山秘闻",
                    "state": "active", "tasks": [{"current": 1, "required": 1}]}],
        "bell": {"near": False, "activated": False, "id": ""},
    }
    bridge.joinpath("state.json").write_text(json.dumps(state), encoding="utf-8")
    bridge.joinpath("assist_request.txt").write_text("quest", encoding="utf-8")
    svc = PbzService(plugin, cfg, tmp_path / "data")

    async def run():
        await svc._tick()
        assert plugin.calls[-1]["ai_behavior"] == "respond"
        prompt = plugin.calls[-1]["parts"][0]["text"]
        assert "[即时陪玩请求]" in prompt
        assert "白山秘闻" in prompt
        assert "当前任务" in prompt
        assert not bridge.joinpath("assist_request.txt").exists()
        await svc.stop()

    asyncio.run(run())
