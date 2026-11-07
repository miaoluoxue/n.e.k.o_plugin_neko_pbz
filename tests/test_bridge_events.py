from __future__ import annotations

import json
import time

from plugin.plugins.neko_pbz.core.bridge import Bridge
from plugin.plugins.neko_pbz.core.events import EventEngine


def _state(**player):
    return {
        "version": 1, "ts": time.time(), "seq": 1,
        "game": {"cutscene": False, "menu_open": False},
        "world": {"id": "XiGu", "name": "悲泣溪谷"},
        "player": {
            "hp_percent": 100, "in_combat": False, "dead": False,
            "shachi": {"percent": 80, "current": 80, "max": 100},
            "equipment": {"main_weapon": {"id": "Weapon_001", "name": "黑伤",
                                          "tier": 2},
                          "phantom_edges": [], "accessories": []},
            **player,
        },
        "enemies": [], "boss": None, "quests": [],
        "bell": {"near": False, "activated": False, "id": ""},
    }


def test_bridge_roundtrip(tmp_path):
    b = Bridge(tmp_path)
    assert b.read_state() is None
    b.root.joinpath("state.json").write_text(json.dumps(_state()), encoding="utf-8")
    assert b.read_state()["world"]["id"] == "XiGu"
    b.write_reply("先敲铃。", priority="P1", ttl=5)
    assert b.read_reply()["text"] == "先敲铃。"
    line = b.reply_text_path.read_text(encoding="utf-8")
    assert line.count("|") == 3 and line.endswith("先敲铃。\n")


def test_event_engine_low_hp_death_and_boss():
    e = EventEngine()
    assert e.step(_state()) == []
    low = e.step(_state(hp_percent=30))
    assert any(x["type"] == "low_hp" for x in low)
    dead = e.step(_state(hp_percent=0, dead=True))
    assert any(x["type"] == "death" for x in dead)
    revived = e.step(_state(hp_percent=60))
    assert any(x["type"] == "respawn" for x in revived)


def test_event_engine_boss_and_bell():
    e = EventEngine()
    e.step(_state())
    s = _state(in_combat=True)
    s["boss"] = {"id": "boss.mu_xiaokui", "name": "沐小葵", "hp_percent": 100,
                 "phase": 1}
    s["bell"] = {"near": True, "activated": False, "id": "bell_1",
                 "name": "杀气塔", "distance": 5}
    events = e.step(s)
    kinds = {x["type"] for x in events}
    assert {"boss_spawn", "bell_near", "combat_start"} <= kinds
