"""Read-only state capability diagnostics for the panel and chat tools."""

from __future__ import annotations

from typing import Any, Dict, List


def _number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def diagnose_state(state: Dict[str, Any]) -> Dict[str, Any]:
    state = state if isinstance(state, dict) else {}
    player = state.get("player") or {}
    world = state.get("world") or {}
    equipment = player.get("equipment") or {}
    capabilities = state.get("capabilities") or {}
    safe_mode = bool(capabilities.get("safe_mode"))
    vitals = capabilities.get("vitals") or {}
    equipment_caps = capabilities.get("equipment") or {}
    enemy_classes = capabilities.get("enemy_classes") or []
    quests = state.get("quests") or []

    checks: List[Dict[str, Any]] = []

    def add(key: str, label: str, ok: bool, detail: str,
            severity: str = "warning") -> None:
        checks.append({
            "key": key, "label": label, "ok": bool(ok),
            "detail": detail, "severity": severity if not ok else "ok",
        })

    hp_ok = _number(player.get("hp_percent")) or (
        _number(player.get("hp")) and _number(player.get("max_hp")))
    add("vitals.hp", "生命值", bool(hp_ok),
        "已读取生命与最大生命" if hp_ok else "未读取到生命；战斗提醒会降级")
    shachi_ok = _number((player.get("shachi") or {}).get("percent")) or any(
        bool(vitals.get(key)) for key in ("shachi", "shachi_max"))
    add("vitals.shachi", "杀气", bool(shachi_ok),
        "已读取杀气" if shachi_ok else "未读取到杀气；资源提醒会降级")
    add("world.map", "区域/地图", bool(world.get("id") or world.get("name")),
        "已读取当前区域" if world.get("id") or world.get("name") else "未读取当前区域")
    add("enemies.classes", "敌人识别", bool(enemy_classes) or safe_mode,
        ("安全模式：已暂停全场景敌人扫描" if safe_mode else
         f"发现 {len(enemy_classes)} 个可疑敌人类" if enemy_classes
         else "未发现敌人类；前方侦察可能为空"), "info")
    add("equipment.main", "主武器", bool(
        equipment.get("main_weapon") or equipment.get("main_weapons")
        or equipment_caps.get("main_weapon")),
        "已读取当前主武器" if equipment.get("main_weapon")
        or equipment.get("main_weapons") or equipment_caps.get("main_weapon")
        else "未读取当前主武器")
    edge_count = len(equipment.get("phantom_edges") or [])
    add("equipment.edges", "影之武装", edge_count > 0,
        f"已读取 {edge_count} 个影之武装槽" if edge_count
        else "影之武装槽为空或字段未适配", "info")
    quest_ok = any(isinstance(q, dict) and q.get("name") for q in quests)
    add("quests.names", "任务名称", quest_ok,
        "已读取当前任务名称" if quest_ok else "没有活动任务，或任务名称字段未适配", "info")
    add("bridge.state", "状态新鲜度", bool(state), 
        "游戏状态可读" if state else "尚未收到游戏状态", "critical")

    total = len(checks)
    passed = sum(1 for check in checks if check["ok"])
    warnings = [check["detail"] for check in checks
                if not check["ok"] and check["severity"] in ("warning", "critical")]
    return {
        "score": round(passed / total * 100) if total else 0,
        "passed": passed,
        "total": total,
        "checks": checks,
        "warnings": warnings,
        "probe": {
            "safe_mode": safe_mode,
            "vitals": vitals,
            "enemy_classes": enemy_classes[:12],
            "equipment": equipment_caps,
        },
    }
