from __future__ import annotations

import random
from pathlib import Path

from plugin.plugins.neko_pbz.core.knowledge import KnowledgeStore
from plugin.plugins.neko_pbz.core.memory import MemoryStore, resolve_save_key

SEED = "data/knowledge/seed.json"
SEED_DIR = Path("data/knowledge")


def test_memory_boss_history_and_digest(tmp_path):
    db = MemoryStore(tmp_path / "m.db")
    key = "player@XiGu"
    db.touch_save(key, character_name="black", world_id="XiGu")
    boss = {"id": "boss.mu_xiaokui", "name": "沐小葵"}
    db.record_event(key, {"type": "boss_spawn", "ts": 1, "data": {}}, current_boss=boss)
    db.record_event(key, {"type": "boss_spawn", "ts": 2, "data": {}}, current_boss=boss)
    db.record_event(key, {"type": "death", "ts": 3, "data": {}}, current_boss=boss)
    db.record_event(key, {"type": "boss_phase", "ts": 4,
                          "data": {"hp_percent": 40}}, current_boss=boss)
    row = db.boss_history(key)[0]
    assert row["attempts"] == 2 and row["deaths"] == 1
    assert row["best_hp_percent"] == 40
    assert "沐小葵" in db.digest(key)
    save_dirs = [p for p in db.root.iterdir()
                 if p.is_dir() and not p.name.startswith("_")]
    assert save_dirs and (save_dirs[0] / "bosses.json").exists()
    assert (save_dirs[0] / "sessions").exists()
    assert db.export(key)["bosses.json"]["boss.mu_xiaokui"]["deaths"] == 1
    db.close()


def test_save_key_prefers_explicit_slot():
    assert resolve_save_key({"save": {"slot": "3"}}) == "slot:3"


def test_save_key_is_stable_across_maps():
    a = resolve_save_key({"player": {"name": "black"}, "world": {"id": "XiGu"}})
    b = resolve_save_key({"player": {"name": "black"}, "world": {"id": "PangZhen"}})
    assert a == b == "black@default"


def test_knowledge_seed_and_tip_selection(tmp_path):
    kb = KnowledgeStore(tmp_path / "k.db", SEED)
    stats = kb.stats()
    assert stats["entities"] >= 10
    assert stats["tips"] >= 6
    tips = kb.select_tips(
        {"id": "boss.mu_xiaokui", "name": "沐小葵"},
        {"main_weapon": {"type": "ranged"},
         "phantom_edges": [{"id": "edge.shachi_hook", "tags": "mobility"}]},
        spoiler_level=1, k_min=1, k_max=3, rng=random.Random(7))
    assert 1 <= len(tips) <= 3
    assert all("待核验" not in x for x in tips)
    assert "背包" not in " ".join(tips)


def test_soulcasting_knowledge_has_no_inventory_counts(tmp_path):
    kb = KnowledgeStore(tmp_path / "k.db", SEED)
    item = kb.get("催心琵琶", spoiler_level=2)
    assert item and item["facts"]["soulcasting"]["next_form"] == "幻术琵琶"
    assert "have" not in str(item["facts"])


def test_all_seed_categories_load_and_filter(tmp_path):
    kb = KnowledgeStore(tmp_path / "all.db")
    for path in sorted(SEED_DIR.glob("seed*.json")):
        kb.load_seed(path)
    coverage = kb.coverage()
    assert coverage["boss"] >= 8
    assert coverage["weapon"] >= 10
    assert coverage["phantom_edge"] >= 10
    assert coverage["accessory"] >= 8
    assert coverage["medicine"] >= 6
    assert coverage["playbook"] >= 3
    assert coverage["region"] >= 6
    bosses = kb.search("", type="boss", limit=50, spoiler_level=2)
    assert len(bosses) >= 8
    meds = kb.search("", type="medicine", limit=50, spoiler_level=2)
    assert any(x["name"] == "苦叶露" for x in meds)
