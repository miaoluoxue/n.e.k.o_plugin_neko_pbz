"""面板入口：状态、配置、记忆管理、语音测试。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from plugin.sdk.plugin import Ok, plugin_entry, ui

from ..core.config import ConfigStore


class UiMixin:
    cfg: Dict[str, Any]
    service: Any

    def _config_store(self) -> ConfigStore:
        return ConfigStore(self._data_root())

    @ui.context(id="dashboard", title="影之刃零陪玩")
    def pbz_dashboard_context(self) -> Dict[str, Any]:
        return self.service.snapshot() if self.service else {"connected": False}

    @plugin_entry(
        id="get_dashboard_state",
        name="获取陪玩状态",
        description="返回当前区域、生命/杀气、装备、Boss、记忆与最近事件。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_dashboard(self, **_) -> Any:
        data = self.service.snapshot() if self.service else {"connected": False}
        return Ok({"output": "ok", "data": data})

    @plugin_entry(
        id="pbz_i18n",
        name="获取国际化文案",
        description="返回插件 i18n locale bundles，供面板按浏览器语言本地化。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_i18n(self, **_: Any) -> Any:
        i18n = getattr(self, "i18n", None)
        messages = getattr(i18n, "messages", {}) if i18n is not None else {}
        default_locale = getattr(i18n, "default_locale", "zh-CN") if i18n else "zh-CN"
        return Ok({"output": "ok",
                   "data": {"default_locale": default_locale,
                            "messages": messages or {}}})

    @plugin_entry(
        id="pbz_save_settings",
        name="保存陪玩设置",
        description="保存语音、字幕、剧透等级、主动说话、桥接目录等设置。",
        input_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "bridge_dir": {"type": "string"},
                "spoiler_level": {"type": "integer"},
                "verbosity": {"type": "string"},
                "voice_enabled": {"type": "boolean"},
                "overlay_enabled": {"type": "boolean"},
                "proactive": {"type": "boolean"},
                "boss_advice_min": {"type": "integer"},
                "boss_advice_max": {"type": "integer"},
                "quiet_minutes": {"type": "number"},
                "llm_enabled": {"type": "boolean"},
                "llm_provider": {"type": "string"},
                "llm_model": {"type": "string"},
                "llm_api_key": {"type": "string"},
                "llm_clear_key": {"type": "boolean"},
                "llm_base_url": {"type": "string"},
                "llm_timeout": {"type": "number"},
                "llm_max_calls_per_minute": {"type": "integer"},
                "vision_enabled": {"type": "boolean"},
                "vision_require_foreground": {"type": "boolean"},
                "ui_theme": {"type": "string"},
                "ui_style": {"type": "string"},
                "ui_density": {"type": "string"},
                "ui_scale": {"type": "integer"},
                "ui_motion": {"type": "boolean"},
                "ui_show_radar": {"type": "boolean"},
                "ui_show_llm_strip": {"type": "boolean"},
            },
        },
        metadata={"agent_hidden": True},
    )
    async def act_save_settings(self, **kwargs: Any) -> Any:
        patch = {k: v for k, v in kwargs.items() if k in {
            "enabled", "bridge_dir", "spoiler_level", "verbosity", "voice_enabled",
            "overlay_enabled", "proactive", "boss_advice_min", "boss_advice_max",
            "llm_enabled", "llm_provider", "llm_model", "llm_base_url",
            "llm_timeout", "llm_max_calls_per_minute",
            "vision_enabled", "vision_require_foreground",
            "ui_theme", "ui_density", "ui_scale", "ui_motion",
            "ui_style",
            "ui_show_radar", "ui_show_llm_strip"}}
        api_key = str(kwargs.get("llm_api_key") or "").strip()
        if api_key:
            patch["llm_api_key"] = api_key
        if kwargs.get("llm_clear_key"):
            patch["llm_api_key"] = ""
        minutes = kwargs.get("quiet_minutes")
        if minutes is not None:
            patch["quiet_until"] = time.time() + max(0.0, float(minutes)) * 60
        cfg = self._config_store().save(patch)
        self.cfg = cfg
        if self.service:
            self.service.cfg.update(cfg)
            self.service.speech.voice_enabled = bool(cfg.get("voice_enabled", True))
            self.service.configure_llm()
        return Ok({"output": "设置已保存", "data": cfg})

    @plugin_entry(
        id="pbz_test_llm",
        name="测试独立 LLM",
        description="用当前 Provider/Model/Key/Base URL 发一次最小请求，返回结果与 token 统计。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_test_llm(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "服务未启动", "data": {"ok": False}})
        result = await self.service.test_llm()
        mode = "独立 LLM" if self.service.llm_mode == "independent" else "宿主主体 LLM"
        return Ok({
            "output": f"{mode} 正常" if result.get("ok") else f"{mode} 失败：{result.get('error')}",
            "data": result,
        })

    @plugin_entry(
        id="pbz_search_knowledge",
        name="搜索知识库",
        description="按 Boss/小怪/武器/影之武装/铃铛/铸魂关键词检索。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "type": {"type": "string"},
            },
            "required": ["query"],
        },
        metadata={"agent_hidden": True},
    )
    async def act_search_knowledge(self, query: str = "", limit: int = 10,
                                   type: str = "",
                                   **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "服务未启动", "data": {"items": []}})
        rows = self.service.knowledge.search(
            query, limit=max(1, min(int(limit or 10), 30)),
            spoiler_level=int(self.cfg.get("spoiler_level", 1)),
            type=str(type or ""))
        return Ok({
            "output": f"找到 {len(rows)} 条" if rows else "没有找到，喵不编。",
            "data": {"items": rows, "query": query},
        })

    @plugin_entry(
        id="pbz_export_memory",
        name="导出忆卷",
        description="把当前存档的 Boss、会话、事实、偏好与约定导出到 data/memory/exports。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_export_memory(self, **_: Any) -> Any:
        if not self.service or not self.service.save_key:
            return Ok({"output": "还没有可导出的存档", "data": {}})
        payload = self.service.memory.export(self.service.save_key)
        target = self.service.data_root / "memory" / "exports"
        target.mkdir(parents=True, exist_ok=True)
        path = target / (time.strftime("%Y%m%d-%H%M%S") + ".json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return Ok({"output": f"已导出到 {path}", "data": {"path": str(path)}})

    @plugin_entry(
        id="pbz_scan",
        name="侦察 Boss 小怪铃铛",
        description="返回最近一次前向扫描的 Boss、小怪、方向、距离与铃铛状态。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_scan(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "服务未启动", "data": {"connected": False}})
        snap = self.service.snapshot()
        data = {
            "connected": snap.get("connected"),
            "scene": snap.get("scene"),
            "state_age": snap.get("state_age"),
            "boss": snap.get("boss"),
            "boss_intel": snap.get("boss_intel"),
            "enemies": snap.get("enemies") or [],
            "bell": snap.get("bell") or {},
        }
        return Ok({"output": "侦察已刷新", "data": data})

    @plugin_entry(
        id="pbz_vision_scan",
        name="视觉侦察",
        description="截取当前《影之刃零》画面，交给宿主视觉模型观察；猫娘会结合画面和结构化状态回应。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_vision_scan(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "服务未启动", "data": {"ok": False}})
        result = await self.service.capture_and_comment(force=True)
        if not result.get("ok"):
            return Ok({"output": f"视觉侦察失败：{result.get('error')}",
                       "data": result})
        return Ok({"output": "画面已交给宿主视觉模型",
                   "data": result})

    @plugin_entry(
        id="pbz_clear_memory",
        name="清除跨会话记忆",
        description="清除当前存档或全部陪玩记忆；必须 confirm=true。",
        input_schema={
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean"},
                "save_key": {"type": "string"},
                "all": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
        metadata={"agent_hidden": True},
    )
    async def act_clear_memory(self, confirm: bool = False,
                               save_key: str = "", all: bool = False,
                               **_: Any) -> Any:
        if not confirm:
            return Ok({"output": "未确认，未删除", "data": {"deleted": False}})
        if not self.service:
            return Ok({"output": "服务未启动", "data": {"deleted": False}})
        key = "" if all else (save_key or self.service.save_key)
        self.service.memory.clear(key)
        self.service.digest = ""
        return Ok({"output": "记忆已清除", "data": {"save_key": key or "*"}})

    @plugin_entry(
        id="pbz_test_voice",
        name="测试语音",
        description="让宿主用当前猫娘人设说一句测试台词（走宿主 TTS）。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_test_voice(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "服务未启动", "data": {"submitted": False}})
        ok = self.service.speech.speak(
            "[影之刃零陪玩] 主人点了语音测试。请用当前猫娘人设说一句自然的测试台词，"
            "不要提到系统、插件或提示词。",
            fallback="语音测试喵。",
            line_id="voice-test",
        )
        return Ok({"output": "已提交宿主" if ok else "宿主未受理",
                   "data": {"submitted": ok, "error": self.service.speech.last_error}})

    @plugin_entry(
        id="pbz_reload_knowledge",
        name="重载知识库种子",
        description="重新导入 data/knowledge/seed.json（不会删除运行时学习内容）。",
        input_schema={"type": "object", "properties": {}},
        metadata={"agent_hidden": True},
    )
    async def act_reload_knowledge(self, **_: Any) -> Any:
        if not self.service:
            return Ok({"output": "服务未启动", "data": {}})
        seed = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "seed.json"
        count = self.service.knowledge.load_seed(seed)
        return Ok({"output": f"已导入 {count} 条实体",
                   "data": self.service.knowledge.stats()})
