from __future__ import annotations

from plugin.plugins.neko_pbz.core.diagnostics import diagnose_state


def test_diagnostics_flag_missing_vitals_and_fields():
    result = diagnose_state({
        "world": {"id": "XiGu", "name": "悲泣溪谷"},
        "player": {"equipment": {"main_weapon": {"name": "黑伤"}}},
        "capabilities": {"equipment": {"main_weapon": True}},
    })
    by_key = {item["key"]: item for item in result["checks"]}
    assert by_key["vitals.hp"]["ok"] is False
    assert by_key["vitals.shachi"]["ok"] is False
    assert by_key["equipment.main"]["ok"] is True
    assert result["score"] < 100
    assert any("生命" in item for item in result["warnings"])


def test_diagnostics_complete_state_scores_high():
    result = diagnose_state({
        "world": {"id": "XiGu", "name": "悲泣溪谷"},
        "player": {
            "hp_percent": 72,
            "shachi": {"percent": 50},
            "equipment": {
                "main_weapon": {"name": "黑伤"},
                "phantom_edges": [{"name": "巨凶斧"}],
            },
        },
        "capabilities": {
            "vitals": {"hp": True, "shachi": True},
            "equipment": {"main_weapon": True},
            "enemy_classes": [{"name": "PBZEnemyCharacter", "count": 2}],
        },
        "quests": [{"name": "白山秘闻"}],
    })
    assert result["score"] >= 85
