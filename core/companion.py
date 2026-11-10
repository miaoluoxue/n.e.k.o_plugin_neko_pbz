"""事件 → 给宿主 LLM 的提示词（不生成固定台词）。"""

from __future__ import annotations

from typing import Any, Dict, List

MOOD_HINT = {
    "death": "心疼、克制，先接情绪",
    "respawn": "松一口气，鼓励但不催",
    "critical_hp": "紧张、短促",
    "low_hp": "担心，提醒拉开",
    "shachi_low": "提醒节奏，不责备",
    "boss_spawn": "专注、带着期待",
    "boss_phase": "紧张，提醒变化",
    "victory": "兴奋、具体地夸",
    "bell_near": "轻松提醒",
    "enemy_spotted": "警觉、简短",
    "combat_start": "进入状态",
    "weapon_changed": "好奇、评价手感",
    "equipment_changed": "注意变化",
    "quest_progress": "认真、简短确认",
    "zone_change": "好奇、放松",
    "player_damaged": "关心",
}


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "未知"


def _equipped(state: Dict[str, Any]) -> str:
    eq = ((state.get("player") or {}).get("equipment") or {})
    weapon = eq.get("main_weapon") or {}
    bits = []
    weapons = eq.get("main_weapons") or ([weapon] if weapon else [])
    names = [w.get("name") for w in weapons if isinstance(w, dict) and w.get("name")]
    if names:
        bits.append("武器 " + "、".join(names))
    secondary = eq.get("secondary_weapon") or {}
    if secondary.get("name") and secondary.get("name") not in names:
        bits.append(f"副武器 {secondary.get('name')}")
    edges = [e.get("name") for e in eq.get("phantom_edges") or []
             if isinstance(e, dict) and e.get("name")]
    if edges:
        bits.append("影之武装 " + "、".join(edges))
    acc = [
        str(x.get("name") or x.get("id")) if isinstance(x, dict) else str(x)
        for x in eq.get("accessories") or [] if x
    ]
    if acc:
        bits.append("饰品 " + "、".join(acc))
    meds = [m.get("name") for m in eq.get("medicines") or []
            if isinstance(m, dict) and m.get("name")]
    if meds:
        bits.append("药品 " + "、".join(meds))
    return "；".join(bits) or "未读到装备"


def _enemy_line(state: Dict[str, Any]) -> str:
    enemies = state.get("enemies") or []
    if not enemies:
        return "视野内暂未读到敌人"
    parts = []
    for e in enemies[:5]:
        if not isinstance(e, dict):
            continue
        name = e.get("name") or e.get("archetype") or "未知敌人"
        dist = e.get("distance")
        dist_txt = f"{float(dist):.0f}米" if isinstance(dist, (int, float)) else ""
        direction = {"front": "正前", "front_left": "左前", "front_right": "右前",
                     "left": "左侧", "right": "右侧", "behind": "后方"}.get(
                         str(e.get("direction") or ""), "")
        parts.append(f"{direction}{name}{('，' + dist_txt) if dist_txt else ''}")
    return "；".join(parts) or "视野内有敌人"


class PromptBuilder:
    def build(self, event: Dict[str, Any], state: Dict[str, Any], *,
              memory_digest: str = "", tips: List[str] | None = None,
              spoiler_level: int = 1) -> Dict[str, str]:
        kind = str(event.get("type") or "")
        data = event.get("data") or {}
        player = state.get("player") or {}
        world = state.get("world") or {}
        boss = state.get("boss") or {}
        bell = state.get("bell") or {}
        quests = state.get("quests") or []

        facts: List[str] = []
        if world.get("name") or world.get("id"):
            facts.append(f"区域：{world.get('name') or world.get('id')}")
        if player:
            facts.append(f"生命：{_pct(player.get('hp_percent'))}")
            shachi = player.get("shachi") or {}
            if shachi.get("percent") is not None:
                facts.append(f"杀气：{_pct(shachi.get('percent'))}")
            facts.append("装备：" + _equipped(state))
        if boss:
            facts.append(f"Boss：{boss.get('name') or boss.get('id') or '未知'}"
                         f"（{_pct(boss.get('hp_percent'))}）")
        if bell:
            state_txt = "已激活" if bell.get("activated") else "未激活"
            facts.append(f"铃铛：{bell.get('name') or bell.get('id') or '附近'}"
                         f"，{state_txt}，{bell.get('distance', '?')}米")
        if kind == "death":
            context = data.get("context") or {}
            if isinstance(context, dict) and context:
                death_boss = context.get("boss") or {}
                facts.append(
                    "死亡前："
                    f"生命 {context.get('hp_percent', '?')}%，"
                    f"杀气 {context.get('shachi_percent', '?')}%，"
                    f"Boss {death_boss.get('name') or death_boss.get('id') or '无'}"
                    f" {death_boss.get('hp_percent', '?')}%")
                enemies = context.get("enemies") or []
                if enemies:
                    facts.append("死亡前附近目标：" + "、".join(
                        str(e.get("name") or "未知") for e in enemies[:4]
                        if isinstance(e, dict)))
        if kind == "enemy_spotted":
            facts.append("前方：" + _enemy_line(state))
        if quests:
            q = quests[0]
            if isinstance(q, dict):
                facts.append(f"任务：{q.get('name') or q.get('id') or ''}".rstrip("："))

        prompt = [
            "[影之刃零陪玩事件]",
            f"事件：{kind}",
            "当前事实：",
            *[f"- {x}" for x in facts if x],
        ]
        if tips:
            prompt.append("可用建议（不要全部照念，按局面自然选 1~3 条；不足就少说）：")
            prompt.extend(f"- {t}" for t in tips)
        if memory_digest:
            prompt.append("跨会话记忆（只用于语气和呼应，不要逐条复述）：")
            prompt.append(memory_digest)
        prompt += [
            "要求：",
            "1. 用当前猫娘人设自然回应，不要自称助手或游戏工具。",
            "2. 先接情绪，再给信息；战斗紧张时短，探索时可以多说一句。",
            "3. 只使用上面给出的事实；没有的数据不要编，尤其不要声称知道背包或材料数量。",
            f"4. 剧透等级 {spoiler_level}：不要提前透露未到的剧情/阶段。",
            "5. 不要输出标题、列表、坐标或内部字段名；1~3 句自然口语。",
        ]
        fallback = self._fallback(kind, data, state)
        return {"prompt": "\n".join(prompt), "fallback": fallback,
                "mood": MOOD_HINT.get(kind, "平静")}

    @staticmethod
    def _fallback(kind: str, data: Dict[str, Any], state: Dict[str, Any]) -> str:
        boss = state.get("boss") or {}
        if kind == "death":
            return "先缓一下，喵在这儿。"
        if kind == "critical_hp":
            return "血太少了，先拉开！"
        if kind == "low_hp":
            return "注意血量，别硬吃这一下。"
        if kind == "shachi_low":
            return "杀气不够了，先稳一手。"
        if kind == "boss_spawn":
            name = boss.get("name") or "Boss"
            return f"{name}来了，先看清起手。"
        if kind == "bell_near":
            return "前面有铃铛，先敲一下再走。"
        if kind == "victory":
            return "赢了！这次打得漂亮。"
        if kind == "enemy_spotted":
            return _enemy_line(state)
        return ""
