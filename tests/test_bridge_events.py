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


def test_reply_queue_waits_for_lua_ack(tmp_path):
    b = Bridge(tmp_path)
    first = b.write_reply("第一条", line_id="line-1")
    b.write_reply("第二条", line_id="line-2")
    assert first["id"] == "line-1"
    assert b.read_reply()["text"] == "第一条"
    assert not (b.root / "reply_ack.txt").exists()

    (b.root / "reply_ack.txt").write_text('{"id":"line-1"}', encoding="utf-8")
    assert b.poll_reply_ack() == "line-1"
    assert b.read_reply()["text"] == "第二条"


def test_bridge_reads_easycsv_slots(tmp_path):
    b = Bridge(tmp_path)
    state_dir = b.root / "state"
    state_dir.mkdir()
    (state_dir / "New_CSV.csv").write_text(
        json.dumps(_state()), encoding="utf-8")
    status_dir = b.root / "mod_status"
    status_dir.mkdir()
    (status_dir / "New_CSV.csv").write_text(
        json.dumps({"state_ready": True, "overlay_ready": False}),
        encoding="utf-8")
    game_hb = b.root / "game_heartbeat"
    game_hb.mkdir()
    (game_hb / "New_CSV.csv").write_text(
        json.dumps({"game_seq": 3}), encoding="utf-8")
    assert b.read_state()["world"]["id"] == "XiGu"
    assert b.read_mod_status()["state_ready"] is True
    assert b.read_game_heartbeat()["game_seq"] == 3


def test_bridge_prefers_newer_root_state_over_stale_easycsv(tmp_path):
    b = Bridge(tmp_path)
    stale = _state()
    stale["ts"] = time.time() - 600
    stale["seq"] = 1
    b.game_state_path.parent.mkdir()
    b.game_state_path.write_text(json.dumps(stale), encoding="utf-8")
    fresh = _state()
    fresh["ts"] = time.time()
    fresh["seq"] = 2
    b.state_path.write_text(json.dumps(fresh), encoding="utf-8")
    assert b.read_state()["seq"] == 2


def test_bridge_ignores_newer_invalid_state_versions(tmp_path):
    b = Bridge(tmp_path)
    valid = _state()
    valid["ts"] = time.time() - 10
    valid["seq"] = 7
    b.state_path.write_text(json.dumps(valid), encoding="utf-8")
    invalid = _state()
    invalid["ts"] = time.time()
    invalid["version"] = "not-a-version"
    b.game_state_path.parent.mkdir()
    b.game_state_path.write_text(json.dumps(invalid), encoding="utf-8")

    assert b.read_state()["seq"] == 7


def test_bridge_prefers_newer_root_status_and_heartbeat(tmp_path):
    b = Bridge(tmp_path)
    b.mod_status_path.parent.mkdir()
    b.mod_status_path.write_text(json.dumps({
        "ts": time.time() - 100, "state_ready": False,
    }), encoding="utf-8")
    (b.root / "mod_status.json").write_text(json.dumps({
        "ts": time.time(), "state_ready": True,
    }), encoding="utf-8")
    b.game_heartbeat_path.parent.mkdir()
    b.game_heartbeat_path.write_text(json.dumps({
        "ts": time.time() - 100, "game_seq": 1,
    }), encoding="utf-8")
    (b.root / "game_heartbeat.json").write_text(json.dumps({
        "ts": time.time(), "game_seq": 2,
    }), encoding="utf-8")
    assert b.read_mod_status()["state_ready"] is True
    assert b.read_game_heartbeat()["game_seq"] == 2


def test_bridge_reads_utf16_easycsv_json(tmp_path):
    b = Bridge(tmp_path)
    state_dir = b.root / "state"
    state_dir.mkdir()
    (state_dir / "New_CSV.csv").write_text(
        json.dumps(_state()), encoding="utf-16")
    assert b.read_state()["world"]["id"] == "XiGu"


def test_bridge_consumes_assist_request_once(tmp_path):
    b = Bridge(tmp_path)
    path = b.root / "assist_request.txt"
    path.write_text("quest", encoding="utf-8")
    assert b.consume_assist_request() == "quest"
    assert not path.exists()
    assert b.consume_assist_request() == ""


def test_bridge_atomically_claims_duplicate_hotkey_requests(tmp_path):
    b = Bridge(tmp_path)
    path = b.root / "vision_request.txt"
    path.write_text("1", encoding="utf-8")
    claimed_a = b._claim(path)
    claimed_b = b._claim(path)
    assert claimed_a is not None
    assert claimed_b is None
    claimed_a.unlink()


def test_event_engine_low_hp_death_and_boss():
    e = EventEngine()
    assert e.step(_state()) == []
    low = e.step(_state(hp_percent=30))
    assert any(x["type"] == "low_hp" for x in low)
    dead = e.step(_state(hp_percent=0, dead=True))
    death = next(x for x in dead if x["type"] == "death")
    assert death["data"]["context"]["hp_percent"] == 30
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
