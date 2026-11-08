"""宿主 LLM 工具：只回答当前事实与知识，不碰背包。"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from plugin.sdk.plugin import Ok, llm_tool


def _equipped(state: Dict[str, Any]) -> Dict[str, Any]:
    return ((state.get("player") or {}).get("equipment") or {})


class ToolMixin:
    service: Any

    def _state(self) -> Dict[str, Any]:
        return (self.service.last_state if self.service else {}) or {}

    @llm_tool(
        name="pbz_status",
        description="读取《影之刃零》当前局面：区域、生命、杀气、战斗状态、Boss、铃铛、当前装备。只读，不含背包。",
        parameters={"type": "object", "properties": {}},
    )
    async def tool_pbz_status(self, **_: Any) -> Any:
        state = self._state()
        if not state:
            return Ok({"output": "还没收到游戏状态：确认游戏已启动、Mod 已加载、桥接心跳正常。"})
        p, w = state.get("player") or {}, state.get("world") or {}
        eq = _equipped(state)
        weapon = eq.get("main_weapon") or {}
        edges = [e.get("name") for e in eq.get("phantom_edges") or []
                 if isinstance(e, dict)]
        lines = [
            f"区域：{w.get('name') or w.get('id') or '未知'}",
            f"生命：{p.get('hp_percent', '?')}%",
            f"杀气：{(p.get('shachi') or {}).get('percent', '?')}%",
            f"战斗：{'是' if p.get('in_combat') else '否'}",
            f"主武器：{weapon.get('name') or '未读到'}",
            f"影之武装：{'、'.join(x for x in edges if x) or '未读到'}",
        ]
        boss = state.get("boss") or {}
        if boss:
            lines.append(f"Boss：{boss.get('name') or boss.get('id')} "
                         f"({boss.get('hp_percent', '?')}%)")
        bell = state.get("bell") or {}
        if bell.get("near"):
            lines.append(f"铃铛：{bell.get('name') or bell.get('id') or '附近'}，"
                         f"{'已激活' if bell.get('activated') else '未激活'}")
        return Ok({"output": "\n".join(lines)})

    @llm_tool(
        name="pbz_control",
        description="按玩家自然语言控制陪玩：静默/恢复、主动说话、字幕、语音、即时陪玩和剧透等级。",
        parameters={
            "type": "object",
            "properties": {
                "quiet_minutes": {"type": "number", "description": "静默分钟数；0 表示解除静默"},
                "proactive": {"type": "boolean"},
                "overlay_enabled": {"type": "boolean"},
                "voice_enabled": {"type": "boolean"},
                "assist_enabled": {"type": "boolean"},
                "spoiler_level": {"type": "integer", "description": "0/1/2"},
            },
        },
    )
    async def tool_pbz_control(self, quiet_minutes: Any = None,
                               proactive: Any = None,
                               overlay_enabled: Any = None,
                               voice_enabled: Any = None,
                               assist_enabled: Any = None,
                               spoiler_level: Any = None,
                               **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "陪玩服务未启动。"})
        patch: Dict[str, Any] = {}
        if quiet_minutes is not None:
            try:
                minutes = max(0.0, float(quiet_minutes))
            except (TypeError, ValueError):
                minutes = 0.0
            patch["quiet_until"] = time.time() + minutes * 60 if minutes else 0.0
        for key, value in (
            ("proactive", proactive),
            ("overlay_enabled", overlay_enabled),
            ("voice_enabled", voice_enabled),
            ("assist_enabled", assist_enabled),
        ):
            if value is not None:
                patch[key] = bool(value)
        if spoiler_level is not None:
            try:
                patch["spoiler_level"] = max(0, min(2, int(spoiler_level)))
            except (TypeError, ValueError):
                pass
        if not patch:
            return Ok({"output": "没有需要调整的陪玩设置。"})
        cfg = self.service.apply_settings(patch)
        bits = []
        if quiet_minutes is not None:
            bits.append("已解除静默" if not cfg.get("quiet_until")
                        else f"安静 {minutes:g} 分钟")
        if "proactive" in patch:
            bits.append("允许主动说话" if patch["proactive"] else "只回应、不主动开口")
        if "overlay_enabled" in patch:
            bits.append("游戏字幕开" if patch["overlay_enabled"] else "游戏字幕关")
        if "voice_enabled" in patch:
            bits.append("宿主语音开" if patch["voice_enabled"] else "宿主语音关")
        if "assist_enabled" in patch:
            bits.append("即时陪玩开" if patch["assist_enabled"] else "即时陪玩关")
        if "spoiler_level" in patch:
            bits.append(f"剧透等级 {cfg.get('spoiler_level')}")
        return Ok({"output": "；".join(bits) or "设置已更新", "data": cfg})

    @llm_tool(
        name="pbz_diagnostics",
        description="检查游戏状态读取能力：生命、杀气、敌人、装备、任务和桥接是否正常，指出缺失字段。",
        parameters={"type": "object", "properties": {}},
    )
    async def tool_pbz_diagnostics(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "陪玩服务未启动。"})
        data = self.service.snapshot().get("diagnostics") or {}
        warnings = data.get("warnings") or []
        heading = (f"状态读取完整度 {data.get('score', 0)}%"
                   f"（{data.get('passed', 0)}/{data.get('total', 0)}）")
        if warnings:
            return Ok({"output": heading + "\n" + "\n".join(f"- {x}" for x in warnings),
                       "data": data})
        return Ok({"output": heading + "\n当前关键字段均已读到。", "data": data})

    @llm_tool(
        name="pbz_session_goal",
        description="设置、查看、完成或清除本局目标。目标会进入跨会话摘要和即时陪玩上下文。",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "目标；留空查看当前目标"},
                "complete": {"type": "boolean", "description": "把当前目标标记完成"},
                "clear": {"type": "boolean", "description": "清除当前目标"},
            },
        },
    )
    async def tool_pbz_session_goal(self, text: str = "",
                                    complete: bool = False,
                                    clear: bool = False,
                                    **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "陪玩服务未启动。"})
        if complete:
            result = self.service.complete_session_goal()
            if not result.get("ok"):
                return Ok({"output": str(result.get("error") or "当前没有可完成的目标")})
            return Ok({"output": f"本局目标已完成：{result['goal'].get('text', '')}"})
        if clear:
            result = self.service.set_session_goal("")
            if not result.get("ok"):
                return Ok({"output": str(result.get("error") or "没有可清除的目标")})
            return Ok({"output": "本局目标已清除"})
        if text.strip():
            result = self.service.set_session_goal(text.strip())
            if not result.get("ok"):
                return Ok({"output": str(result.get("error") or "目标保存失败")})
            return Ok({"output": f"本局目标：{result['goal']['text']}"})
        goal = self.service.snapshot().get("goal") or {}
        if goal.get("text") and goal.get("status") == "active":
            return Ok({"output": f"本局目标：{goal['text']}"})
        return Ok({"output": "本局还没有设置目标。"})

    @llm_tool(
        name="pbz_last_death",
        description="查看最近一次死亡前的局面快照，用于复盘而不是重复泛泛安慰。",
        parameters={"type": "object", "properties": {}},
    )
    async def tool_pbz_last_death(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "陪玩服务未启动。"})
        data = self.service.snapshot().get("last_death") or {}
        context = data.get("context") or {}
        if not context:
            return Ok({"output": "还没有记录到死亡前局面。"})
        boss = context.get("boss") or {}
        enemies = context.get("enemies") or []
        return Ok({
            "output": (
                f"上次死亡前生命 {context.get('hp_percent', '?')}%，"
                f"杀气 {context.get('shachi_percent', '?')}%，"
                f"Boss {boss.get('name') or boss.get('id') or '无'}"
                f" {boss.get('hp_percent', '?')}%；附近目标 {len(enemies)} 个。"
            ),
            "data": data,
        })

    @llm_tool(
        name="pbz_what_ahead",
        description="回答主人“前面有什么怪”：使用最近一次前向扫描结果，报方位、距离、数量与类型；没有数据就明说。",
        parameters={"type": "object", "properties": {}},
    )
    async def tool_pbz_what_ahead(self, **_: Any) -> Any:
        enemies = self._state().get("enemies") or []
        if not enemies:
            return Ok({"output": "最近的扫描范围内没有读到敌人。喵不能据此保证前面绝对安全。"})
        parts = []
        for e in enemies[:8]:
            if not isinstance(e, dict):
                continue
            name = e.get("name") or e.get("archetype") or "未知敌人"
            dist = e.get("distance")
            direction = e.get("direction") or ""
            parts.append(f"{direction} {name}" + (f"，约 {dist} 米" if dist is not None else ""))
        return Ok({"output": f"前方读到 {len(enemies)} 个目标：" + "；".join(parts)})

    @llm_tool(
        name="pbz_boss_info",
        description="查询 Boss 知识：所在区域、首领组、攻略短记、危险动作、应对方向与本地历史。用于战前提示或复盘。",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Boss 名称；留空用当前 Boss"}},
        },
    )
    async def tool_pbz_boss_info(self, name: str = "", **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "陪玩服务未启动。"})
        boss = self._state().get("boss") or {}
        key = name or boss.get("name") or boss.get("id") or ""
        if not key:
            return Ok({"output": "现在没有正在面对的 Boss；告诉喵具体名字也可以查。"})
        entity = self.service.knowledge.get(
            str(key), spoiler_level=int(self.service.cfg.get("spoiler_level", 1)))
        history = self.service.memory.boss_history(self.service.save_key, limit=8)
        mine = next((h for h in history
                     if key in (h.get("boss_name"), h.get("boss_id"))), None)
        bits = []
        if entity:
            facts = entity.get("facts") or {}
            bits.append(f"{entity.get('name')}（{entity.get('type')}）")
            for k in ("summary", "map_world_label", "boss_group", "phases",
                      "threat", "recommended_defense", "arena", "guide_note", "tip"):
                if facts.get(k):
                    bits.append(f"{k}: {facts[k]}")
            if entity.get("hidden_by_spoiler"):
                bits.append("详细内容被剧透等级隐藏")
        else:
            bits.append(f"知识库里还没有「{key}」的可靠条目，喵不编。")
        if mine:
            bits.append("本地记录：尝试 {attempts} 次，死亡 {deaths} 次，"
                        "最好 {best}%".format(
                            attempts=mine.get("attempts", 0), deaths=mine.get("deaths", 0),
                            best=round(mine.get("best_hp_percent") or 0)))
        return Ok({"output": "；".join(bits)})

    @llm_tool(
        name="pbz_player_state",
        description="读取玩家当前状态：生命、杀气、当前主武器/影之武装/饰品。明确不含背包、仓库或材料数量。",
        parameters={"type": "object", "properties": {}},
    )
    async def tool_pbz_player_state(self, **_: Any) -> Any:
        state = self._state()
        if not state:
            return Ok({"output": "还没收到玩家状态。"})
        p = state.get("player") or {}
        eq = _equipped(state)
        payload = {
            "hp_percent": p.get("hp_percent"),
            "shachi": p.get("shachi") or {},
            "in_combat": p.get("in_combat"),
            "main_weapon": eq.get("main_weapon"),
            "main_weapons": eq.get("main_weapons") or [],
            "secondary_weapon": eq.get("secondary_weapon"),
            "phantom_edges": eq.get("phantom_edges") or [],
            "accessories": eq.get("accessories") or [],
            "medicines": eq.get("medicines") or [],
            "note": "未读取背包/材料数量",
        }
        return Ok({"output": json.dumps(payload, ensure_ascii=False)})

    @llm_tool(
        name="pbz_kb_search",
        description="搜索《影之刃零》知识库：Boss、任务、路线、收集物、NPC、物品、小怪、武器、影之武装、饰品、铃铛、铸魂、机制。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "type": {"type": "string", "description": "boss/quest/route/collectible/npc/item/mob/weapon/phantom_edge/accessory/medicine/mechanic/playbook/region/bell/guide"},
            },
            "required": ["query"],
        },
    )
    async def tool_pbz_kb_search(self, query: str = "", limit: int = 6,
                                 type: str = "",
                                 **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "知识库未启动。"})
        rows = self.service.knowledge.search(
            query, limit=max(1, min(int(limit or 6), 12)),
            spoiler_level=int(self.service.cfg.get("spoiler_level", 1)),
            type=str(type or ""))
        if not rows:
            return Ok({"output": f"知识库里没有「{query}」，喵不编。"})
        out = []
        for r in rows:
            facts = r.get("facts") or {}
            hints = facts.get("acquisition_hints") or []
            brief = (facts.get("summary") or facts.get("guide_note")
                     or (hints[0] if hints else "")
                     or facts.get("tip") or facts.get("use")
                     or facts.get("category") or "")
            out.append(f"{r.get('name')}（{r.get('type')}）{brief}")
        return Ok({"output": "；".join(out)})

    @llm_tool(
        name="pbz_quest_info",
        description="查询任务的分步目标、区域、前置、失败提醒与奖励。留空时读取当前任务；也可传任务名。",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "任务名称；留空用当前任务"}},
        },
    )
    async def tool_pbz_quest_info(self, name: str = "", **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "知识库未启动。"})
        names = []
        if name.strip():
            names.append(name.strip())
        else:
            for quest in self._state().get("quests") or []:
                if not isinstance(quest, dict):
                    continue
                label = str(quest.get("name") or quest.get("id") or "").strip()
                if label:
                    names.append(label)
        if not names:
            return Ok({"output": "现在没读到当前任务；告诉喵任务名也可以查。"})
        level = int(self.service.cfg.get("spoiler_level", 1))
        chunks = []
        for label in names[:3]:
            entity = self.service.knowledge.get(label, spoiler_level=level)
            if not entity or entity.get("type") != "quest":
                rows = self.service.knowledge.search(
                    label, limit=1, spoiler_level=level, type="quest")
                entity = rows[0] if rows else None
            if not entity or entity.get("hidden_by_spoiler"):
                continue
            facts = entity.get("facts") or {}
            lines = [str(entity.get("name") or label)]
            if facts.get("summary"):
                lines.append(str(facts["summary"]))
            for index, step in enumerate(facts.get("steps") or [], 1):
                if not isinstance(step, dict):
                    continue
                text = step.get("instruction") or step.get("title") or ""
                if text:
                    lines.append(f"{index}. {text}")
                if index >= 8:
                    break
            notes = facts.get("guide_notes") or []
            if notes:
                lines.append("提醒：" + str(notes[-1]))
            rewards = facts.get("rewards") or []
            if rewards:
                lines.append("奖励：" + "、".join(str(x) for x in rewards[:8]))
            chunks.append("\n".join(lines))
        if not chunks:
            return Ok({"output": f"任务库里没有「{'、'.join(names[:3])}」的可靠记录，喵不编。"})
        return Ok({"output": "\n\n".join(chunks)})

    @llm_tool(
        name="pbz_assist",
        description="让猫娘根据当前局面即时陪玩：快速局面提醒、当前任务下一步、Boss提醒或本局复盘。",
        parameters={
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": ["brief", "quest", "boss", "review"],
                    "description": "brief=当前局面，quest=任务，boss=Boss，review=本局复盘",
                },
            },
        },
    )
    async def tool_pbz_assist(self, focus: str = "brief", **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "陪玩服务未启动。"})
        result = await self.service.request_assist(focus, source="chat")
        if not result.get("ok"):
            return Ok({"output": str(result.get("error") or "现在还不能即时陪玩")})
        return Ok({"output": "已经把当前情况交给猫娘，她正在回应。"})

    @llm_tool(
        name="pbz_playbook",
        description="查询《影之刃零》玩法库：战前准备、战斗节奏、探索/铃铛、铸魂、配装槽位等。",
        parameters={
            "type": "object",
            "properties": {"topic": {"type": "string"}},
        },
    )
    async def tool_pbz_playbook(self, topic: str = "", **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "玩法库未启动。"})
        rows = self.service.knowledge.search(
            topic, limit=8,
            spoiler_level=int(self.service.cfg.get("spoiler_level", 1)),
            type="playbook")
        if not rows:
            rows = self.service.knowledge.search(
                topic, limit=8,
                spoiler_level=int(self.service.cfg.get("spoiler_level", 1)),
                type="mechanic")
        if not rows:
            return Ok({"output": f"玩法库里没有「{topic}」，喵不编。"})
        bits = []
        for row in rows:
            facts = row.get("facts") or {}
            steps = facts.get("steps") or []
            bits.append(f"{row.get('name')}：" + "；".join(steps or [facts.get("tip", "")]))
        return Ok({"output": "\n".join(x for x in bits if x.strip())})

    @llm_tool(
        name="pbz_look",
        description="看主人当前《影之刃零》游戏画面。主人在问画面里的敌人/Boss/铃铛/地形，或猫娘需要视觉确认时调用。返回一帧游戏截图给宿主视觉模型。",
        parameters={"type": "object", "properties": {}},
    )
    async def tool_pbz_look(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "画面感知未启动。"})
        result = self.service.capture_for_tool()
        if not result.get("ok"):
            return Ok({"output": f"没能看到游戏画面：{result.get('error')}"})
        return {
            "output": {"captured": True,
                       "size": [result.get("width"), result.get("height")],
                       "note": "这是主人当前游戏画面；看不清的内容不要编。"},
            "images": [{
                "data_b64": result.get("data_b64", ""),
                "mime": result.get("mime", "image/jpeg"),
                "vision_prompt": (
                    "这是《影之刃零》的当前游戏画面。请观察玩家状态、Boss/小怪、"
                    "铃铛、地形和可交互物体；只描述确实看得到的内容，"
                    "不确定的名字不要编造。"
                ),
            }],
        }

    @llm_tool(
        name="pbz_memory_recall",
        description="回忆与主人玩《影之刃零》的跨会话经历：上次卡关、Boss 尝试、偏好、约定。",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )
    async def tool_pbz_memory_recall(self, query: str = "", **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "记忆库未启动。"})
        digest = self.service.memory.digest(self.service.save_key)
        if not digest:
            return Ok({"output": "还没有跨会话记忆；这一局结束后喵会记下关键经历。"})
        if query:
            lines = [x for x in digest.splitlines() if query in x]
            if lines:
                return Ok({"output": "\n".join(lines[:8])})
        return Ok({"output": digest})

    @llm_tool(
        name="pbz_set_preference",
        description="记录玩家偏好，例如安静、剧透边界、喜欢的打法。只记录偏好，不记录背包。",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    )
    async def tool_pbz_set_preference(self, key: str = "", value: str = "",
                                      **_: Any) -> Any:
        if not self.service or not key:
            return Ok({"output": "没有可记录的偏好。"})
        profile = self.service.memory.set_preferences({key: value})
        return Ok({"output": f"记住了：{key}={value}",
                   "data": profile.get("preferences")})

    @llm_tool(
        name="pbz_remember_promise",
        description="记录与主人的约定，例如“下次先试幻术琵琶”。下次游戏会主动提起。",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "due_hint": {"type": "string"},
            },
            "required": ["text"],
        },
    )
    async def tool_pbz_remember_promise(self, text: str = "",
                                        due_hint: str = "", **_: Any) -> Any:
        if not self.service or not text.strip():
            return Ok({"output": "没有可记录的约定。"})
        pid = self.service.memory.add_promise(self.service.save_key, text.strip(), due_hint)
        return Ok({"output": f"约好了：{text}", "data": {"id": pid}})

    @llm_tool(
        name="pbz_soulcasting_info",
        description="查询武器/影之武装的铸魂形态链、材料来源与铸魂后能力。只查知识，不读材料持有量。",
        parameters={
            "type": "object",
            "properties": {"weapon": {"type": "string"}},
        },
    )
    async def tool_pbz_soulcasting_info(self, weapon: str = "", **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "知识库未启动。"})
        if not weapon:
            weapon = ((_equipped(self._state()).get("main_weapon") or {}).get("name") or "")
        if not weapon:
            return Ok({"output": "现在没读到主武器；告诉喵武器名也可以查。"})
        entity = self.service.knowledge.get(
            weapon, spoiler_level=int(self.service.cfg.get("spoiler_level", 1)))
        if not entity:
            return Ok({"output": f"知识库里还没有「{weapon}」的铸魂条目，喵不编。"})
        soul = (entity.get("facts") or {}).get("soulcasting") or {}
        if not soul:
            return Ok({"output": f"「{weapon}」目前没有可靠的铸魂资料。"})
        bits = [f"{entity.get('name')}：{soul.get('current_form', '')} → "
                f"{soul.get('next_form', '')}"]
        mats = soul.get("materials") or []
        if mats:
            bits.append("需要：" + "、".join(
                f"{m.get('name')}×{m.get('qty')}" for m in mats if isinstance(m, dict)))
        if soul.get("new_abilities"):
            bits.append("铸魂后：" + "、".join(soul["new_abilities"]))
        bits.append("持有量未知（不读背包）")
        return Ok({"output": "；".join(bits)})
