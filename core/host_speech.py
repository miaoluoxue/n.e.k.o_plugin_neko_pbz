"""宿主语音/对话桥。

`respond` 让宿主用当前猫娘人设生成台词并 TTS；插件再从
`ctx.bus.conversations` 拉取最终 AI 文本，写回游戏字幕，保证“听到的”和
“屏幕上看到的”是同一句。

`read` 只注入上下文，不触发 TTS。
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple


def _unwrap(result: Any) -> list:
    if result is None:
        return []
    is_err = getattr(result, "is_err", None)
    if callable(is_err) and is_err():
        return []
    for field in ("value", "items", "_items", "records"):
        inner = getattr(result, field, None)
        if isinstance(inner, list):
            return inner
    if isinstance(result, list):
        return result
    try:
        out = list(result)
        return out
    except Exception:
        return []


def _role(turn_type: str) -> str:
    t = (turn_type or "").lower()
    return "human" if any(x in t for x in ("instruction", "user_message", "human")) else "ai"


class ConversationWatcher:
    """轮询宿主 conversations，按到达时间游标增量读取。"""

    def __init__(self, ctx: Any, lanlan_name: str = "") -> None:
        self.ctx = ctx
        self.lanlan_name = lanlan_name
        self.last_ts = time.time()
        self.supported = self._resolve() is not None

    def _resolve(self) -> Any:
        bus = getattr(self.ctx, "bus", None) if self.ctx else None
        conv = getattr(bus, "conversations", None) if bus else None
        return conv if callable(getattr(conv, "get", None)) else None

    async def poll(self) -> List[Tuple[str, str, float, str]]:
        conv = self._resolve()
        if conv is None:
            return []
        try:
            result = conv.get(since_ts=float(self.last_ts), max_count=50, timeout=2.0)
            if hasattr(result, "__await__"):
                result = await result
        except Exception:
            return []
        out: List[Tuple[str, str, float, str]] = []
        max_ts = self.last_ts
        for rec in _unwrap(result):
            try:
                ts = float(getattr(rec, "timestamp", 0) or 0)
                if ts > max_ts:
                    max_ts = ts
                if ts <= self.last_ts:
                    continue
                name = str(getattr(rec, "lanlan_name", "") or "")
                if self.lanlan_name and name and name != self.lanlan_name:
                    continue
                text = str(getattr(rec, "content", "") or "").strip()
                if not text:
                    continue
                turn_type = str(getattr(rec, "turn_type", "") or "")
                out.append((_role(turn_type), text, ts, turn_type))
            except Exception:
                continue
        self.last_ts = max_ts
        return out


class HostSpeech:
    """把事实提示交给宿主，并回收最终台词。"""

    def __init__(self, plugin: Any, *, voice_enabled: bool = True,
                 lanlan_name: str = "") -> None:
        self.plugin = plugin
        self.voice_enabled = bool(voice_enabled)
        self.pending_ts = 0.0
        self.pending_fallback = ""
        self.pending_id = ""
        self.last_error = ""
        self.watcher = ConversationWatcher(getattr(plugin, "ctx", None), lanlan_name)

    def _push_parts(self, parts: List[Dict[str, Any]], *, behavior: str,
                    visibility: List[str]) -> bool:
        push = getattr(self.plugin, "push_message", None)
        if not callable(push):
            self.last_error = "push_message unavailable"
            return False
        try:
            kwargs: Dict[str, Any] = dict(
                parts=parts,
                visibility=visibility,
                ai_behavior=behavior,
            )
            ctx = getattr(self.plugin, "ctx", None)
            target = str(getattr(ctx, "lanlan_name", "") or os.environ.get("NEKO_CHARACTER", "")).strip()
            if target:
                kwargs["target_lanlan"] = target
            try:
                result = push(**kwargs)
            except TypeError:
                kwargs.pop("target_lanlan", None)
                result = push(**kwargs)
            if isinstance(result, dict) and (
                    result.get("submitted") is False or result.get("ok") is False):
                self.last_error = str(result.get("reason") or "host rejected")
                return False
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def _push(self, text: str, *, behavior: str, visibility: List[str]) -> bool:
        return self._push_parts([{"type": "text", "text": text}],
                                behavior=behavior, visibility=visibility)

    def speak(self, prompt: str, *, fallback: str = "", line_id: str = "") -> bool:
        prompt = str(prompt or "").strip()
        if not prompt:
            return False
        if not self.voice_enabled:
            # 不播报时只作为上下文，不制造无声的“回复”。
            return self._push(prompt, behavior="read", visibility=[])
        ok = self._push(prompt, behavior="respond", visibility=["chat"])
        if ok:
            self.pending_ts = time.time()
            self.pending_fallback = fallback
            self.pending_id = line_id
        return ok

    def note_context(self, text: str) -> bool:
        return self._push(text, behavior="read", visibility=[])

    def speak_image(self, prompt: str, image_bytes: bytes, mime: str = "image/jpeg",
                    *, fallback: str = "", line_id: str = "") -> bool:
        """把文字提示 + 游戏截图交给宿主视觉模型，并触发猫娘回复/TTS。"""
        if not image_bytes:
            return self.speak(prompt, fallback=fallback, line_id=line_id)
        if not self.voice_enabled:
            return self._push_parts([
                {"type": "text", "text": prompt},
                {"type": "image", "data": image_bytes, "mime": mime},
            ], behavior="read", visibility=[])
        ok = self._push_parts([
            {"type": "text", "text": str(prompt or "").strip()},
            {"type": "image", "data": image_bytes, "mime": mime},
        ], behavior="respond", visibility=["chat"])
        if ok:
            self.pending_ts = time.time()
            self.pending_fallback = fallback
            self.pending_id = line_id
        return ok

    def note_vision(self, prompt: str, image_bytes: bytes,
                    mime: str = "image/jpeg") -> bool:
        """只把截图注入宿主视觉上下文，不额外触发一轮回复。"""
        return self._push_parts([
            {"type": "text", "text": prompt},
            {"type": "image", "data": image_bytes, "mime": mime},
        ], behavior="read", visibility=[])

    def notify_user(self, text: str) -> bool:
        """系统/面板消息：用户可见，但不触发 AI/TTS。"""
        return self._push(text, behavior="blind", visibility=["chat"])

    async def poll_final(self) -> Optional[Dict[str, Any]]:
        """返回 pending 之后宿主生成的最终 AI 台词。"""
        if not self.pending_ts:
            return None
        turns = await self.watcher.poll()
        for role, text, ts, turn_type in turns:
            if role != "ai" or ts < self.pending_ts - 0.05:
                continue
            result = {"text": text, "ts": ts, "turn_type": turn_type,
                      "id": self.pending_id, "fallback": self.pending_fallback}
            self.pending_ts = 0.0
            self.pending_fallback = ""
            self.pending_id = ""
            return result
        return None

    @property
    def waiting(self) -> bool:
        return bool(self.pending_ts)
