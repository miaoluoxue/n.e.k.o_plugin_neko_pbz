from __future__ import annotations

from plugin.plugins.neko_pbz.core.companion import PromptBuilder


def _state():
    return {
        "world": {"id": "XiGu", "name": "悲泣溪谷"},
        "player": {
            "hp_percent": 28, "in_combat": True,
            "shachi": {"percent": 12},
            "equipment": {
                "main_weapon": {"name": "黑伤", "type": "single_blade"},
                "phantom_edges": [{"name": "追命锁镰"}],
                "accessories": ["AC_Health"],
            },
        },
        "boss": {"id": "boss.mu_xiaokui", "name": "沐小葵", "hp_percent": 70},
        "enemies": [{"name": "弓手", "distance": 18, "direction": "front_right"}],
        "quests": [], "bell": {},
    }


def test_prompt_is_grounded_and_forbids_inventory_claims():
    built = PromptBuilder().build(
        {"type": "boss_spawn", "data": {}}, _state(),
        memory_digest="- 上次卡在沐小葵", tips=["先敲铃", "杀气见底先拉开"])
    prompt = built["prompt"]
    assert "沐小葵" in prompt and "追命锁镰" in prompt
    assert "不要声称知道背包" in prompt
    assert "1~3 句" in prompt
    assert "先敲铃" in prompt


def test_fallback_never_invents_inventory():
    built = PromptBuilder().build({"type": "low_hp", "data": {}}, _state())
    assert "药" not in built["fallback"]
