"""状态 → 陪玩事件。

只做事实差分，不生成台词。所有阈值集中在这里，方便实机调。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(player: Dict[str, Any]) -> Optional[float]:
    raw = player.get("hp_percent")
    if raw is not None:
        return _num(raw, -1.0)
    hp, mx = _num(player.get("hp"), -1.0), _num(player.get("max_hp"), 0.0)
    if hp >= 0 and mx > 0:
        return hp / mx * 100.0
    return None


def _sig(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "|".join(sorted(str(x) for x in items))


class EventEngine:
    """有状态的事件差分器。"""

    def __init__(self) -> None:
        self.prev: Dict[str, Any] = {}
        self._low_hp = False
        self._critical = False
        self._shachi_low = False
        self._dead = False
        self._bell_id = ""
        self._quests: Dict[str, str] = {}
        self._enemy_sig = ""
        self._last_viable: Dict[str, Any] = {}

    def reset(self) -> None:
        self.__init__()

    def step(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        now = time.time()
        events: List[Dict[str, Any]] = []
        player = state.get("player") or {}
        game = state.get("game") or {}
        world = state.get("world") or {}
        prev_player = (self.prev.get("player") or {}) if self.prev else {}
        prev_world = (self.prev.get("world") or {}) if self.prev else {}

        def emit(kind: str, priority: str, **data: Any) -> None:
            events.append({"version": 1, "ts": now, "type": kind,
                           "priority": priority, "source": "structured", "data": data})

        # 区域
        wid, prev_wid = str(world.get("id") or ""), str(prev_world.get("id") or "")
        if self.prev and wid and wid != prev_wid:
            emit("zone_change", "P2", world_id=wid, name=str(world.get("name") or ""))

        # 战斗
        combat = bool(player.get("in_combat"))
        if self.prev and combat and not bool(prev_player.get("in_combat")):
            emit("combat_start", "P1", enemy_count=len(state.get("enemies") or []))
        if self.prev and not combat and bool(prev_player.get("in_combat")):
            emit("combat_end", "P2")

        # 生命
        hp = _pct(player)
        prev_hp = _pct(prev_player) if prev_player else None
        if hp is not None:
            if hp <= 18 and not self._critical:
                self._critical = True
                emit("critical_hp", "P0", hp_percent=round(hp, 1))
            elif hp > 25:
                self._critical = False
            if hp <= 35 and not self._low_hp:
                self._low_hp = True
                emit("low_hp", "P0", hp_percent=round(hp, 1))
            elif hp >= 45:
                self._low_hp = False
            if prev_hp is not None and hp < prev_hp - 8 and hp > 0:
                emit("player_damaged", "P1",
                     hp_percent=round(hp, 1), drop=round(prev_hp - hp, 1))
            elif prev_hp is not None and hp > prev_hp + 8:
                emit("healed", "P2", hp_percent=round(hp, 1))

        # 死亡 / 复活
        dead = bool(player.get("dead")) or (hp is not None and hp <= 0)
        if dead and not self._dead:
            self._dead = True
            emit("death", "P0", context=dict(self._last_viable))
        elif not dead and self._dead:
            self._dead = False
            emit("respawn", "P0")
        if not dead:
            boss_now = state.get("boss") or {}
            eq_now = player.get("equipment") or {}
            self._last_viable = {
                "hp_percent": round(hp, 1) if hp is not None else None,
                "shachi_percent": (
                    round(_num((player.get("shachi") or {}).get("percent")), 1)
                    if (player.get("shachi") or {}).get("percent") is not None else None
                ),
                "in_combat": bool(player.get("in_combat")),
                "world": str(world.get("name") or world.get("id") or ""),
                "boss": {
                    "id": str(boss_now.get("id") or boss_now.get("name") or ""),
                    "name": str(boss_now.get("name") or ""),
                    "hp_percent": boss_now.get("hp_percent"),
                    "phase": boss_now.get("phase"),
                } if boss_now else {},
                "enemies": [
                    {
                        "name": str(e.get("name") or e.get("id") or ""),
                        "distance": e.get("distance"),
                        "direction": e.get("direction"),
                    }
                    for e in (state.get("enemies") or [])[:8]
                    if isinstance(e, dict)
                ],
                "equipment": {
                    "main_weapon": (eq_now.get("main_weapon") or {}).get("name") or "",
                    "phantom_edges": [
                        e.get("name") for e in eq_now.get("phantom_edges") or []
                        if isinstance(e, dict)
                    ],
                    "accessories": [
                        a.get("name") if isinstance(a, dict) else str(a)
                        for a in eq_now.get("accessories") or []
                    ],
                },
            }

        # 杀气
        shachi = player.get("shachi") or {}
        sp = shachi.get("percent")
        if sp is not None:
            sp = _num(sp, 100.0)
            if sp <= 15 and not self._shachi_low:
                self._shachi_low = True
                emit("shachi_low", "P1", percent=round(sp, 1))
            elif sp >= 30:
                self._shachi_low = False

        # Boss
        boss = state.get("boss") or {}
        prev_boss = (self.prev.get("boss") or {}) if self.prev else {}
        boss_id = str(boss.get("id") or boss.get("name") or "")
        prev_boss_id = str(prev_boss.get("id") or prev_boss.get("name") or "")
        if boss_id and boss_id != prev_boss_id:
            emit("boss_spawn", "P1", boss_id=boss_id,
                 name=str(boss.get("name") or ""),
                 hp_percent=boss.get("hp_percent"))
        if boss_id and prev_boss_id == boss_id:
            phase, prev_phase = boss.get("phase"), prev_boss.get("phase")
            if prev_phase is not None and phase is not None and phase != prev_phase:
                emit("boss_phase", "P0", boss_id=boss_id, phase=phase,
                     hp_percent=boss.get("hp_percent"))
            bhp, prev_bhp = boss.get("hp_percent"), prev_boss.get("hp_percent")
            if bhp is not None and prev_bhp is not None and _num(bhp, 100) <= 0 < _num(prev_bhp, 0):
                emit("victory", "P0", boss_id=boss_id, name=str(boss.get("name") or ""))
        if prev_boss_id and not boss_id:
            emit("boss_end", "P1", boss_id=prev_boss_id)

        # 铃铛
        bell = state.get("bell") or {}
        bell_id = str(bell.get("id") or "")
        if bell.get("near") and not bell.get("activated"):
            if bell_id and bell_id != self._bell_id:
                self._bell_id = bell_id
                emit("bell_near", "P1", bell_id=bell_id,
                     name=str(bell.get("name") or ""),
                     distance=bell.get("distance"))
        elif not bell.get("near"):
            self._bell_id = ""
        if bell.get("activated") and bell_id:
            prev_bell = (self.prev.get("bell") or {}) if self.prev else {}
            if bell_id != str(prev_bell.get("id") or "") or not prev_bell.get("activated"):
                emit("bell_activated", "P1", bell_id=bell_id,
                     name=str(bell.get("name") or ""))

        # 敌人组合（非战斗或刚发现时）
        enemies = state.get("enemies") or []
        names = [str(e.get("name") or e.get("id") or "") for e in enemies if isinstance(e, dict)]
        sig = _sig(names)
        if enemies and sig and sig != self._enemy_sig and not game.get("cutscene"):
            self._enemy_sig = sig
            emit("enemy_spotted", "P1", count=len(enemies),
                 names=names[:8], enemies=enemies[:8])
        elif not enemies:
            self._enemy_sig = ""

        # 装备（只看当前装备）
        equipment = player.get("equipment") or {}
        prev_eq = (prev_player.get("equipment") or {}) if prev_player else {}
        weapons = equipment.get("main_weapons") or []
        prev_weapons = prev_eq.get("main_weapons") or []
        if not weapons and equipment.get("main_weapon"):
            weapons = [equipment.get("main_weapon")]
        if not prev_weapons and prev_eq.get("main_weapon"):
            prev_weapons = [prev_eq.get("main_weapon")]
        weapon_sig = _sig([w.get("id") or w.get("name") for w in weapons if isinstance(w, dict)])
        prev_weapon_sig = _sig([w.get("id") or w.get("name") for w in prev_weapons
                                if isinstance(w, dict)])
        if self.prev and weapon_sig and weapon_sig != prev_weapon_sig:
            emit("weapon_changed", "P1", weapon=weapons[0] if weapons else {})
        edges = equipment.get("phantom_edges") or []
        prev_edges = prev_eq.get("phantom_edges") or []
        edge_sig = _sig([e.get("id") if isinstance(e, dict) else e for e in edges])
        prev_edge_sig = _sig([e.get("id") if isinstance(e, dict) else e for e in prev_edges])
        if self.prev and edge_sig != prev_edge_sig:
            emit("equipment_changed", "P2", slot="phantom_edges", edges=edges)
        accessories = equipment.get("accessories") or []
        accessory_sig = _sig([a.get("id") or a.get("name") if isinstance(a, dict) else a
                              for a in accessories])
        prev_accessory_sig = _sig([
            a.get("id") or a.get("name") if isinstance(a, dict) else a
            for a in (prev_eq.get("accessories") or [])])
        if self.prev and accessory_sig != prev_accessory_sig:
            emit("equipment_changed", "P2", slot="accessories", accessories=accessories)
        medicines = equipment.get("medicines") or []
        medicine_sig = _sig([m.get("id") or m.get("name") if isinstance(m, dict) else m
                             for m in medicines])
        prev_medicine_sig = _sig([
            m.get("id") or m.get("name") if isinstance(m, dict) else m
            for m in (prev_eq.get("medicines") or [])])
        if self.prev and medicine_sig != prev_medicine_sig:
            emit("equipment_changed", "P2", slot="medicines", medicines=medicines)

        # 任务进度
        for q in state.get("quests") or []:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("id") or q.get("name") or "")
            if not qid:
                continue
            progress = "|".join(
                f"{t.get('current')}/{t.get('required')}/{t.get('complete')}"
                for t in (q.get("tasks") or []) if isinstance(t, dict)
            )
            old = self._quests.get(qid)
            if old is not None and progress and progress != old:
                emit("quest_progress", "P2", quest=qid,
                     name=str(q.get("name") or ""), progress=progress)
            self._quests[qid] = progress

        self.prev = state
        return events
