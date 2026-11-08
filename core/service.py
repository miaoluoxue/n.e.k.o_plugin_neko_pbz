"""后台服务：桥接 → 事件 → 记忆/知识 → 宿主人设回复 → 游戏字幕。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from ..adapters import LLMProvider, LLMThrottle
from ..perception import capture_pbz_window
from .bridge import Bridge
from .companion import PromptBuilder
from .events import EventEngine
from .host_speech import HostSpeech
from .knowledge import KnowledgeStore
from .memory import MemoryStore, resolve_save_key

log = logging.getLogger("neko_pbz.service")

_COOLDOWN = {
    "death": 8.0, "respawn": 10.0, "critical_hp": 15.0, "low_hp": 25.0,
    "shachi_low": 40.0, "boss_spawn": 30.0, "boss_phase": 20.0,
    "victory": 15.0, "bell_near": 60.0, "enemy_spotted": 45.0,
    "combat_start": 60.0, "combat_end": 40.0, "weapon_changed": 20.0,
    "equipment_changed": 30.0, "quest_progress": 90.0, "zone_change": 90.0,
    "player_damaged": 30.0, "healed": 60.0, "boss_end": 20.0,
}

_P0 = {"death", "critical_hp", "boss_phase", "victory"}
_P1 = {"low_hp", "shachi_low", "boss_spawn", "bell_near", "enemy_spotted",
       "combat_start", "weapon_changed", "player_damaged", "respawn"}


class PbzService:
    def __init__(self, plugin: Any, cfg: Dict[str, Any], data_root: Path) -> None:
        self.plugin = plugin
        self.cfg = dict(cfg)
        self.data_root = Path(data_root)
        self.bridge = Bridge(self.cfg["bridge_dir"])
        self.memory = MemoryStore(self.data_root / "memory")
        knowledge_dir = self.data_root / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        seed_root = Path(__file__).resolve().parent.parent / "data" / "knowledge"
        seed_files = sorted(seed_root.glob("seed*.json"))
        persist_seeds = []
        for code_file in seed_files:
            persist_file = knowledge_dir / code_file.name
            # 种子是随插件版本更新的只读默认数据；玩家纠错写 corrections/，不会被覆盖。
            persist_file.write_bytes(code_file.read_bytes())
            persist_seeds.append(persist_file)
        self.knowledge = KnowledgeStore(
            knowledge_dir / "pbz_knowledge.db",
            None,
            corrections_dir=knowledge_dir / "corrections")
        for seed_file in persist_seeds:
            self.knowledge.load_seed(seed_file)
        self.knowledge.apply_corrections()
        self.speech = HostSpeech(
            plugin, voice_enabled=bool(self.cfg.get("voice_enabled", True)))
        self.engine = EventEngine()
        self.prompts = PromptBuilder()
        self.llm = LLMProvider(int(cfg.get("llm_max_calls_per_minute", 10)))
        self.configure_llm()
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._queue: Deque[Dict[str, Any]] = deque(maxlen=64)
        self._last_spoke = 0.0
        self._last_event: Dict[str, float] = {}
        self._last_tip: Dict[str, float] = {}
        self._log: Deque[Dict[str, Any]] = deque(maxlen=int(cfg.get("event_log_limit", 200)))
        self._snapshot: Dict[str, Any] = {"connected": False}
        self.save_key = ""
        self.session_id = 0
        self.digest = ""
        self.digest_ts = 0.0
        self.last_state: Dict[str, Any] = {}
        self._session_deaths = 0
        self._session_victories = 0
        self._session_zones: List[str] = []
        self._last_heartbeat = 0.0
        self.session_started_at = 0.0
        self._last_vision_ts = 0.0
        self._last_vision: Dict[str, Any] = {
            "ok": False, "error": "not_captured", "captured_at": 0.0,
            "width": 0, "height": 0, "submitted": False,
        }
        self._last_assist_ts = 0.0
        self._last_assist: Dict[str, Any] = {
            "focus": "", "submitted": False, "error": "", "ts": 0.0,
        }

    # ── 生命周期 ─────────────────────────
    def _host_llm_call(self):
        for name in ("__call_llm", "call_llm", "__call_intent_llm"):
            fn = getattr(self.plugin, name, None)
            if callable(fn):
                return fn
        return None

    def configure_llm(self) -> None:
        self.llm._throttle = LLMThrottle(
            int(self.cfg.get("llm_max_calls_per_minute", 10)))
        provider = str(self.cfg.get("llm_provider") or "").strip()
        model = str(self.cfg.get("llm_model") or "").strip()
        key = str(self.cfg.get("llm_api_key") or "").strip()
        base = str(self.cfg.get("llm_base_url") or "").strip()
        if self.cfg.get("llm_enabled") and provider and model:
            self.llm.set_client(provider, model, key, base)
            try:
                self.llm._client.timeout = float(self.cfg.get("llm_timeout", 20.0))
            except Exception:
                pass
        else:
            self.llm._client = None
        host = self._host_llm_call()
        if host is None:
            self.llm.set_host_call(None)
        else:
            async def fallback(prompt: str) -> str:
                out = host(prompt)
                if inspect.isawaitable(out):
                    out = await out
                if isinstance(out, dict):
                    out = out.get("output") or out.get("text") or out.get("content") or ""
                return str(out or "").strip()
            self.llm.set_host_call(fallback)

    @property
    def llm_available(self) -> bool:
        return (getattr(self.llm, "_client", None) is not None
                or getattr(self.llm, "_host_call", None) is not None)

    @property
    def llm_mode(self) -> str:
        if getattr(self.llm, "_client", None) is not None:
            return "independent"
        if getattr(self.llm, "_host_call", None) is not None:
            return "host"
        return "none"

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await self._end_session_async()
        try:
            self.bridge.write_heartbeat(status="stopped")
        except Exception:
            pass
        try:
            self.memory.close()
        except Exception:
            pass
        try:
            self.knowledge.close()
        except Exception:
            pass

    async def _loop(self) -> None:
        interval = max(0.15, float(self.cfg.get("poll_interval", 0.35)))
        while not self._stopping:
            try:
                await self._tick()
            except Exception as exc:
                log.warning("pbz tick failed: %s", exc)
            await asyncio.sleep(interval)

    # ── 主循环 ───────────────────────────
    async def _tick(self) -> None:
        if self.bridge.consume_vision_request() and self.cfg.get("vision_enabled", True):
            await self.capture_and_comment(force=True)
        assist_focus = self.bridge.consume_assist_request()
        state = self.bridge.read_state()
        fresh = bool(state) and self.bridge.state_age(state) <= float(
            self.cfg.get("state_stale_seconds", 3.0))
        if fresh and state:
            self.last_state = state
            self._ensure_session(state)
            for event in self.engine.step(state):
                self._queue.append(event)
            for event in self.bridge.read_events():
                self._queue.append(event)
            self._refresh_snapshot(state, connected=True)
        else:
            self._refresh_snapshot(self.last_state, connected=False)

        if assist_focus:
            await self.request_assist(assist_focus, source="hotkey")
        await self._process_queue()
        await self._poll_final()
        now = time.time()
        if now - self._last_heartbeat >= 2.0:
            self._last_heartbeat = now
            try:
                self.bridge.write_heartbeat(
                    game_seq=int((self.last_state or {}).get("seq") or 0),
                    status="ok" if fresh else "stale")
            except Exception:
                pass

    def _ensure_session(self, state: Dict[str, Any]) -> None:
        player = state.get("player") or {}
        world = state.get("world") or {}
        key = resolve_save_key(state, str(self.cfg.get("save_key") or ""))
        if key != self.save_key:
            self._end_session()
            self.save_key = key
            self.session_id = self.memory.start_session(key)
            self.session_started_at = time.time()
            self.memory.touch_save(
                key, character_name=str(player.get("name") or ""),
                game_version=str(state.get("game_version") or ""),
                world_id=str(world.get("id") or ""))
            self._refresh_digest(force=True)

    def _rule_summary(self) -> str:
        parts = []
        if self._session_zones:
            parts.append("去过 " + "、".join(dict.fromkeys(self._session_zones[-4:])))
        if self._session_deaths:
            parts.append(f"死亡 {self._session_deaths} 次")
        if self._session_victories:
            parts.append(f"击败 {self._session_victories} 个 Boss")
        return "；".join(parts)

    async def _end_session_async(self) -> None:
        if not self.session_id:
            return
        summary = self._rule_summary()
        if self.llm_available:
            try:
                generated = await asyncio.wait_for(self._summarize_with_llm(), timeout=9.0)
                if generated:
                    summary = generated
            except Exception:
                pass
        self._end_session(summary)

    async def _summarize_with_llm(self) -> str:
        recent = "\n".join(
            f"- {x.get('type')}: {x.get('text') or x.get('fallback') or ''}"
            for x in list(self._log)[-20:] if x.get("type") != "host_reply")
        prompt = (
            "你在整理一场《影之刃零》陪玩会话的事实记忆。"
            "只根据下面事实，输出 3~5 条中文短句，每条一行，不要口吻、不要推测、"
            "不要提到插件/系统/提示词，不要编造未发生的事。\n"
            f"区域：{', '.join(dict.fromkeys(self._session_zones[-6:]))}\n"
            f"死亡次数：{self._session_deaths}\n"
            f"Boss 击杀：{self._session_victories}\n"
            f"事件：\n{recent or '- 无'}"
        )
        out = await self.llm.call(prompt)
        text = " ".join(str(out or "").split())
        return text[:600]

    async def test_llm(self) -> Dict[str, Any]:
        if not self.llm_available:
            return {"ok": False, "error": "未配置独立 LLM，宿主也没有注入 LLM",
                    "stats": self.llm.snapshot()}
        try:
            out = await asyncio.wait_for(
                self.llm.call("只回复两个字：正常"), timeout=12.0)
            return {"ok": bool(out), "output": out or "",
                    "error": "" if out else "调用失败或限流",
                    "mode": self.llm_mode,
                    "stats": self.llm.snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "stats": self.llm.snapshot()}

    def capture_for_tool(self) -> Dict[str, Any]:
        """给 @llm_tool 用：只截图，不额外触发一轮回复。"""
        if not self.cfg.get("vision_enabled", True):
            return {"ok": False, "error": "画面识别已关闭"}
        result = capture_pbz_window(
            require_foreground=bool(self.cfg.get("vision_require_foreground", True)),
            max_edge=int(self.cfg.get("vision_max_edge", 1024)),
            quality=int(self.cfg.get("vision_jpeg_quality", 80)))
        self._last_vision = {
            "ok": bool(result.get("ok")), "error": result.get("error", ""),
            "captured_at": result.get("captured_at", time.time()),
            "width": result.get("width", 0), "height": result.get("height", 0),
            "submitted": False,
        }
        return result

    def _assist_facts(self, focus: str) -> List[str]:
        state = self.last_state or {}
        player = state.get("player") or {}
        world = state.get("world") or {}
        eq = player.get("equipment") or {}
        boss = state.get("boss") or {}
        bell = state.get("bell") or {}
        quests = state.get("quests") or []
        facts = [
            f"区域：{world.get('name') or world.get('id') or '未知'}",
            f"生命：{player.get('hp_percent', '?')}%",
            f"杀气：{(player.get('shachi') or {}).get('percent', '?')}%",
            f"战斗：{'是' if player.get('in_combat') else '否'}",
            f"主武器：{(eq.get('main_weapon') or {}).get('name') or '未读到'}",
        ]
        edges = [e.get("name") for e in eq.get("phantom_edges") or []
                 if isinstance(e, dict) and e.get("name")]
        if edges:
            facts.append("影之武装：" + "、".join(edges))
        if boss:
            facts.append(
                f"Boss：{boss.get('name') or boss.get('id') or '未知'}"
                f" {boss.get('hp_percent', '?')}%")
        if bell.get("near") or bell.get("activated"):
            facts.append(
                f"铃铛：{bell.get('name') or bell.get('id') or '附近'}"
                f"，{'已激活' if bell.get('activated') else '未激活'}")
        for quest in quests[:3]:
            if not isinstance(quest, dict):
                continue
            tasks = []
            for task in quest.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                current = task.get("current")
                required = task.get("required")
                if current is not None or required is not None:
                    tasks.append(f"{current if current is not None else '?'}/"
                                 f"{required if required is not None else '?'}")
            suffix = f"（{'、'.join(tasks)}）" if tasks else ""
            facts.append(f"当前任务：{quest.get('name') or quest.get('id') or ''}{suffix}")

        level = int(self.cfg.get("spoiler_level", 1))
        if focus == "quest" and quests:
            quest = next((q for q in quests if isinstance(q, dict)), {})
            key = str(quest.get("name") or quest.get("id") or "")
            entity = self.knowledge.get(key, spoiler_level=level) if key else None
            if entity and entity.get("type") == "quest":
                data = entity.get("facts") or {}
                facts.append("任务资料：")
                for index, step in enumerate(data.get("steps") or [], 1):
                    if not isinstance(step, dict):
                        continue
                    text = step.get("instruction") or step.get("title") or ""
                    if text:
                        facts.append(f"- 第{index}步：{text}")
                    if index >= 6:
                        break
                notes = data.get("guide_notes") or []
                if notes:
                    facts.append("- 提醒：" + str(notes[-1]))
            elif key:
                facts.append(f"任务资料：知识库里暂时没有「{key}」的可靠步骤")
        elif focus == "boss" and boss:
            key = str(boss.get("name") or boss.get("id") or "")
            entity = self.knowledge.get(key, spoiler_level=level) if key else None
            if entity:
                data = entity.get("facts") or {}
                for label, field in (
                    ("区域", "map_world_label"),
                    ("首领组", "boss_group"),
                    ("短攻略", "guide_note"),
                    ("应对", "recommended_defense"),
                ):
                    if data.get(field):
                        facts.append(f"Boss{label}：{data[field]}")
            try:
                tips = self.knowledge.select_tips(
                    boss, eq, spoiler_level=level,
                    k_min=int(self.cfg.get("boss_advice_min", 1)),
                    k_max=int(self.cfg.get("boss_advice_max", 3)))
                facts.extend(f"建议：{tip}" for tip in tips)
            except Exception:
                pass
        elif focus == "review":
            facts.append(
                f"本局统计：死亡 {self._session_deaths} 次，"
                f"击败 {self._session_victories} 个 Boss")
            if self._session_zones:
                facts.append("去过：" + "、".join(dict.fromkeys(self._session_zones[-6:])))
            recent = [
                f"{item.get('type')} {item.get('text') or item.get('fallback') or ''}".strip()
                for item in list(self._log)[-10:]
                if item.get("type") != "host_reply"
            ]
            if recent:
                facts.append("最近事件：" + "；".join(recent))
            if self.save_key:
                try:
                    history = self.memory.boss_history(self.save_key, limit=4)
                    for item in history:
                        facts.append(
                            f"Boss记录：{item.get('boss_name') or item.get('boss_id')}，"
                            f"尝试 {item.get('attempts', 0)} 次，死亡 {item.get('deaths', 0)} 次，"
                            f"最好 {round(item.get('best_hp_percent') or 0)}%")
                except Exception:
                    pass
        return facts

    async def request_assist(self, focus: str = "brief", *,
                             source: str = "panel") -> Dict[str, Any]:
        focus = focus if focus in {"brief", "quest", "boss", "review"} else "brief"
        if not self.cfg.get("assist_enabled", True):
            result = {"ok": False, "error": "即时陪玩已关闭", "focus": focus}
            self._last_assist = {"focus": focus, "submitted": False,
                                 "error": result["error"], "ts": time.time()}
            return result
        if not self.last_state or not self._snapshot.get("connected"):
            result = {"ok": False, "error": "游戏状态未连接", "focus": focus}
            self._last_assist = {"focus": focus, "submitted": False,
                                 "error": result["error"], "ts": time.time()}
            return result
        if self.speech.waiting:
            return {"ok": False, "error": "猫娘正在回应上一条消息", "focus": focus}
        now = time.time()
        remaining = float(self.cfg.get("assist_cooldown", 3.0)) - (
            now - self._last_assist_ts)
        if remaining > 0:
            return {"ok": False,
                    "error": f"请稍等 {remaining:.1f} 秒再请求",
                    "focus": focus}

        focus_instruction = {
            "brief": "用一两句点出眼下最值得注意的局面，再给一个可执行的小提醒。",
            "quest": "结合当前任务资料，明确下一步先做什么；不要把后续步骤一次全念完。",
            "boss": "围绕当前 Boss 给战前或战中提醒，只说 1~3 条真正相关的信息。",
            "review": "像并肩打完一局的伙伴那样简短复盘：先接情绪，再指出一个具体得失。",
        }[focus]
        facts = self._assist_facts(focus)
        prompt = "\n".join([
            "[即时陪玩请求]",
            f"触发来源：{source}",
            f"互动焦点：{focus}",
            focus_instruction,
            "当前事实：",
            *[f"- {item}" for item in facts if item],
            "要求：",
            "1. 使用宿主当前猫娘人设，自然回应主人，不要自称助手或游戏工具。",
            "2. 只使用上面的当前事实与任务/Boss资料；没有的信息不要编。",
            "3. 不报内部字段、坐标、JSON、标题或列表。",
            "4. 默认 1~3 句；战斗紧张时更短。",
            f"5. 剧透等级 {int(self.cfg.get('spoiler_level', 1))}，不要提前透露未到剧情。",
        ])
        fallback = {
            "brief": "喵在，先看眼前这一步，别急着抢。",
            "quest": "先按当前任务提示走，别漏掉旁边的交付点。",
            "boss": "先稳住，看准一轮起手再决定接还是躲。",
            "review": "这局先记住这个失误，下一次我们换个节奏。",
        }[focus]
        line_id = self.bridge.next_id(f"assist-{focus}")
        ok = self.speech.speak(prompt, fallback=fallback, line_id=line_id)
        self._last_assist_ts = now
        self._last_assist = {
            "focus": focus, "submitted": bool(ok),
            "error": "" if ok else self.speech.last_error,
            "ts": now, "source": source,
        }
        self._log.append({
            "ts": now, "type": "assist_request", "priority": "P1",
            "focus": focus, "source": source, "submitted": bool(ok),
            "fallback": fallback,
            "error": self.speech.last_error if not ok else "",
        })
        return {"ok": bool(ok), "focus": focus,
                "error": "" if ok else self.speech.last_error,
                "line_id": line_id}

    async def capture_and_comment(self, *, force: bool = False) -> Dict[str, Any]:
        """截图并让宿主视觉模型看，再以猫娘人设回应。"""
        if not self.cfg.get("vision_enabled", True):
            return {"ok": False, "error": "画面识别已关闭"}
        now = time.time()
        cooldown = float(self.cfg.get("vision_cooldown", 8.0))
        if not force and now - self._last_vision_ts < cooldown:
            return {"ok": False, "error": "视觉侦察冷却中"}
        result = self.capture_for_tool()
        if not result.get("ok"):
            self._last_vision["error"] = result.get("error", "截图失败")
            return {"ok": False, "error": self._last_vision["error"]}
        state = self.last_state or {}
        player = state.get("player") or {}
        boss = state.get("boss") or {}
        enemies = state.get("enemies") or []
        bell = state.get("bell") or {}
        facts = [
            f"生命 {player.get('hp_percent', '?')}%",
            f"杀气 {(player.get('shachi') or {}).get('percent', '?')}%",
        ]
        if boss:
            facts.append(f"Boss {boss.get('name') or boss.get('id')} {boss.get('hp_percent', '?')}%")
        if enemies:
            facts.append("敌人 " + "、".join(
                str(e.get("name") or e.get("id") or "未知") for e in enemies[:6]
                if isinstance(e, dict)))
        if bell.get("near") or bell.get("activated"):
            facts.append(f"铃铛 {bell.get('name') or bell.get('id')} "
                         f"{'已激活' if bell.get('activated') else '未激活'}")
        prompt = (
            "[视觉侦察] 主人正在玩《影之刃零》。请结合这张实时游戏画面和下面的结构化事实，"
            "用当前猫娘人设自然说 1~2 句。只描述画面中确实看得到的内容；"
            "看不清的敌人/Boss 不要编名字，不要提插件或提示词。\n"
            "结构化事实：" + "；".join(facts)
        )
        line_id = self.bridge.next_id("vision")
        ok = self.speech.speak_image(
            prompt, result.get("image_bytes") or "",
            result.get("mime", "image/jpeg"),
            fallback="画面看到了，喵在。", line_id=line_id)
        self._last_vision_ts = now
        self._last_vision.update({"ok": True, "error": "", "submitted": bool(ok),
                                  "captured_at": result.get("captured_at", now)})
        return {"ok": True, "submitted": bool(ok), "width": result.get("width"),
                "height": result.get("height"), "error": self.speech.last_error if not ok else ""}

    def _end_session(self, summary: str = "") -> None:
        if not self.session_id:
            return
        summary = summary or self._rule_summary()
        try:
            self.memory.end_session(self.session_id, summary=summary)
        except Exception:
            pass
        self.session_id = 0
        self.session_started_at = 0.0
        self._session_deaths = 0
        self._session_victories = 0
        self._session_zones = []

    def _refresh_digest(self, *, force: bool = False) -> None:
        if not self.save_key:
            self.digest = ""
            return
        if not force and time.time() - self.digest_ts < 30:
            return
        try:
            self.digest = self.memory.digest(self.save_key)
        except Exception:
            self.digest = ""
        self.digest_ts = time.time()

    # ── 事件处理 ─────────────────────────
    async def _process_queue(self) -> None:
        if not self._queue:
            return
        if self.speech.waiting:
            return
        event = self._queue.popleft()
        kind = str(event.get("type") or "")
        data = event.get("data") or {}
        boss = (self.last_state or {}).get("boss") or {}
        try:
            self.memory.record_event(self.save_key, event, current_boss=boss)
        except Exception:
            pass
        if kind == "death":
            self._session_deaths += 1
        elif kind == "victory":
            self._session_victories += 1
        elif kind == "zone_change":
            self._session_zones.append(str(data.get("name") or data.get("world_id") or ""))

        if not self._should_speak(event):
            return
        self._last_event[self._event_key(event)] = time.time()
        self._refresh_digest()
        tips: List[str] = []
        if kind in ("boss_spawn", "boss_gate"):
            try:
                tips = self.knowledge.select_tips(
                    boss or {"name": data.get("name") or "", "id": data.get("boss_id") or ""},
                    ((self.last_state.get("player") or {}).get("equipment") or {}),
                    spoiler_level=int(self.cfg.get("spoiler_level", 1)),
                    k_min=int(self.cfg.get("boss_advice_min", 1)),
                    k_max=int(self.cfg.get("boss_advice_max", 3)),
                )
            except Exception:
                tips = []
        built = self.prompts.build(
            event, self.last_state or {}, memory_digest=self.digest, tips=tips,
            spoiler_level=int(self.cfg.get("spoiler_level", 1)))
        line_id = self.bridge.next_id(kind or "line")
        ok = self.speech.speak(built["prompt"], fallback=built["fallback"], line_id=line_id)
        self._last_spoke = time.time()
        self._log.append({
            "ts": time.time(), "type": kind, "priority": self._priority(kind),
            "submitted": ok, "tips": tips, "fallback": built["fallback"],
            "error": self.speech.last_error if not ok else "",
        })

    def _priority(self, kind: str) -> str:
        if kind in _P0:
            return "P0"
        if kind in _P1:
            return "P1"
        return "P2"

    def _event_key(self, event: Dict[str, Any]) -> str:
        data = event.get("data") or {}
        return "|".join(str(x) for x in (
            event.get("type"), data.get("boss_id") or data.get("bell_id")
            or data.get("weapon") or data.get("quest") or ""))

    def _should_speak(self, event: Dict[str, Any]) -> bool:
        kind = str(event.get("type") or "")
        state = self.last_state or {}
        game = state.get("game") or {}
        if game.get("cutscene") or game.get("menu_open"):
            return False
        if not self.cfg.get("proactive", True) and kind not in _P0:
            return False
        if time.time() < float(self.cfg.get("quiet_until") or 0):
            return False
        now = time.time()
        key = self._event_key(event)
        if now - self._last_event.get(key, 0.0) < _COOLDOWN.get(kind, 30.0):
            return False
        if kind not in _P0 and now - self._last_spoke < 4.0:
            return False
        return True

    # ── 最终台词写回游戏 ─────────────────
    async def _poll_final(self) -> None:
        final = await self.speech.poll_final()
        if final:
            self.bridge.write_reply(
                final["text"], priority=self._priority(
                    str((self._log[-1] or {}).get("type") or "line")) if self._log else "P1",
                ttl=6.0, mood=final.get("turn_type", ""), line_id=final.get("id", ""))
            self._log.append({"ts": time.time(), "type": "host_reply",
                              "text": final["text"], "submitted": True})
            return
        if self.speech.waiting and time.time() - self.speech.pending_ts > float(
                self.cfg.get("host_reply_timeout", 10.0)):
            fallback = self.speech.pending_fallback
            line_id = self.speech.pending_id
            self.speech.pending_ts = 0.0
            self.speech.pending_fallback = ""
            self.speech.pending_id = ""
            if fallback:
                self.bridge.write_reply(fallback, priority="P1", ttl=5.0,
                                        line_id=line_id or "fallback")
                self._log.append({"ts": time.time(), "type": "fallback",
                                  "text": fallback, "submitted": True})

    # ── 面板 ─────────────────────────────
    def _refresh_snapshot(self, state: Dict[str, Any], *, connected: bool) -> None:
        player = state.get("player") or {}
        world = state.get("world") or {}
        eq = player.get("equipment") or {}
        boss = state.get("boss") or {}
        enemies = state.get("enemies") or []
        bell = state.get("bell") or {}
        quests = state.get("quests") or []
        boss_intel = None
        if boss:
            key = boss.get("id") or boss.get("name") or ""
            try:
                entity = self.knowledge.get(
                    str(key), spoiler_level=int(self.cfg.get("spoiler_level", 1)))
                if entity:
                    boss_intel = {
                        "name": entity.get("name"),
                        "facts": entity.get("facts") or {},
                        "hidden_by_spoiler": bool(entity.get("hidden_by_spoiler")),
                    }
            except Exception:
                pass
        scene = self._scene(state)
        history = []
        promises = []
        if self.save_key:
            try:
                history = self.memory.boss_history(self.save_key, limit=5)
                promises = self.memory.open_promises(self.save_key, limit=5)
            except Exception:
                pass
        last_line = ""
        for item in reversed(self._log):
            if item.get("text"):
                last_line = str(item["text"])
                break
        self._snapshot = {
            "connected": connected,
            "scene": scene,
            "state_age": round(self.bridge.state_age(state), 2) if state else None,
            "save_key": self.save_key,
            "session": {
                "seconds": int(time.time() - self.session_started_at) if self.session_started_at else 0,
                "deaths": self._session_deaths,
                "victories": self._session_victories,
                "zones": list(dict.fromkeys(self._session_zones[-6:])),
            },
            "region": world.get("name") or world.get("id") or "",
            "hp_percent": player.get("hp_percent"),
            "shachi_percent": (player.get("shachi") or {}).get("percent"),
            "in_combat": bool(player.get("in_combat")),
            "weapon": (eq.get("main_weapon") or {}).get("name") or "",
            "main_weapons": eq.get("main_weapons") or (
                [eq.get("main_weapon")] if eq.get("main_weapon") else []),
            "secondary_weapon": eq.get("secondary_weapon"),
            "phantom_edges": [e.get("name") for e in eq.get("phantom_edges") or []
                              if isinstance(e, dict)],
            "edges_detail": eq.get("phantom_edges") or [],
            "accessories": eq.get("accessories") or [],
            "medicines": eq.get("medicines") or [],
            "boss": {"name": boss.get("name"), "hp_percent": boss.get("hp_percent"),
                     "phase": boss.get("phase")} if boss else None,
            "boss_intel": boss_intel,
            "bell": bell,
            "quests": [
                {"id": q.get("id"), "name": q.get("name"), "state": q.get("state"),
                 "tasks": q.get("tasks") or []}
                for q in quests[:6] if isinstance(q, dict)
            ],
            "enemies": [{"name": e.get("name"), "distance": e.get("distance"),
                         "direction": e.get("direction")}
                        for e in enemies[:8] if isinstance(e, dict)],
            "memory_digest": self.digest,
            "boss_history": history,
            "promises": promises,
            "last_line": last_line,
            "knowledge": {**self.knowledge.stats(),
                          "coverage": self.knowledge.coverage()},
            "memory": self.memory.stats(),
            "events": list(self._log)[-30:],
            "voice": bool(self.cfg.get("voice_enabled", True)),
            "host_bus": bool(self.speech.watcher.supported),
            "waiting_reply": self.speech.waiting,
            "bridge_dir": str(self.bridge.root),
            "spoiler_level": int(self.cfg.get("spoiler_level", 1)),
            "boss_advice_min": int(self.cfg.get("boss_advice_min", 1)),
            "boss_advice_max": int(self.cfg.get("boss_advice_max", 3)),
            "overlay": bool(self.cfg.get("overlay_enabled", True)),
            "proactive": bool(self.cfg.get("proactive", True)),
            "llm": {
                "enabled": bool(self.cfg.get("llm_enabled")),
                "provider": str(self.cfg.get("llm_provider") or ""),
                "model": str(self.cfg.get("llm_model") or ""),
                "base_url": str(self.cfg.get("llm_base_url") or ""),
                "key_set": bool(str(self.cfg.get("llm_api_key") or "").strip()),
                "available": self.llm_available,
                "mode": self.llm_mode,
                "host_available": getattr(self.llm, "_host_call", None) is not None,
                "timeout": float(self.cfg.get("llm_timeout", 20.0)),
                "rate": int(self.cfg.get("llm_max_calls_per_minute", 10)),
                "stats": self.llm.snapshot(),
            },
            "vision": {
                "enabled": bool(self.cfg.get("vision_enabled", True)),
                "ok": bool(self._last_vision.get("ok")),
                "error": str(self._last_vision.get("error") or ""),
                "captured_at": float(self._last_vision.get("captured_at") or 0),
                "width": int(self._last_vision.get("width") or 0),
                "height": int(self._last_vision.get("height") or 0),
                "submitted": bool(self._last_vision.get("submitted")),
                "cooldown": float(self.cfg.get("vision_cooldown", 8.0)),
                "require_foreground": bool(self.cfg.get("vision_require_foreground", True)),
            },
            "assist": {
                "enabled": bool(self.cfg.get("assist_enabled", True)),
                "cooldown": float(self.cfg.get("assist_cooldown", 3.0)),
                **self._last_assist,
            },
            "ui": {
                "style": str(self.cfg.get("ui_style") or "scroll"),
                "theme": str(self.cfg.get("ui_theme") or "ink"),
                "density": str(self.cfg.get("ui_density") or "comfortable"),
                "scale": int(self.cfg.get("ui_scale", 100) or 100),
                "motion": bool(self.cfg.get("ui_motion", True)),
                "show_radar": bool(self.cfg.get("ui_show_radar", True)),
                "show_llm_strip": bool(self.cfg.get("ui_show_llm_strip", True)),
            },
            "paths": {
                "config": str(self.data_root / "config"),
                "memory": str(self.data_root / "memory"),
                "knowledge": str(self.data_root / "knowledge"),
            },
        }

    @staticmethod
    def _scene(state: Dict[str, Any]) -> str:
        player = state.get("player") or {}
        game = state.get("game") or {}
        if game.get("cutscene") or game.get("menu_open"):
            return "quiet"
        if player.get("dead"):
            return "death"
        hp = player.get("hp_percent")
        try:
            hp = float(hp) if hp is not None else None
        except (TypeError, ValueError):
            hp = None
        if state.get("boss"):
            return "boss"
        if hp is not None and hp <= 25:
            return "critical"
        if hp is not None and hp <= 35:
            return "low_hp"
        if player.get("in_combat"):
            return "combat"
        if state.get("enemies"):
            return "alerted"
        return "exploring"

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._snapshot)
