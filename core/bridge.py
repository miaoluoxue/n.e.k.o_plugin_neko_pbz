"""游戏 Mod ↔ Python 插件的文件桥接。

协议：
  state/New_CSV.csv 游戏 → 插件，覆盖写（EasyCsv 目录槽位）
  events.jsonl   游戏 → 插件，追加写
  reply.json     插件 → 游戏，覆盖写
  heartbeat.json 插件存活信号；game_heartbeat 为游戏侧存活信号

游戏侧 JS 每 250ms 采样；插件侧异步读取，不阻塞宿主命令循环。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = path.read_bytes()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8-sig")
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, ValueError, TypeError):
        return None


class Bridge:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.game_state_path = self.root / "state" / "New_CSV.csv"
        self.mod_status_path = self.root / "mod_status" / "New_CSV.csv"
        self.game_heartbeat_path = self.root / "game_heartbeat" / "New_CSV.csv"
        self.events_path = self.root / "events.jsonl"
        self.reply_path = self.root / "reply.json"
        self.reply_text_path = self.root / "reply.txt"
        self.heartbeat_path = self.root / "heartbeat.json"
        self._events_offset = 0
        self._events_inode = 0
        self._seq = 0

    # ── 读 ────────────────────────────────
    def read_state(self) -> Optional[Dict[str, Any]]:
        state = None
        for path in (self.game_state_path,
                     self.state_path,
                     self.state_path.with_name(self.state_path.name + ".csv"),
                     self.root / "state.csv"):
            state = read_json(path)
            if state is not None:
                break
        if state is None:
            return None
        if int(state.get("version") or 0) != 1:
            return None
        return state

    def read_mod_status(self) -> Optional[Dict[str, Any]]:
        return read_json(self.mod_status_path)

    def read_game_heartbeat(self) -> Optional[Dict[str, Any]]:
        return read_json(self.game_heartbeat_path)

    def state_age(self, state: Optional[Dict[str, Any]] = None) -> float:
        state = state if state is not None else self.read_state()
        if not state:
            return 1e9
        try:
            return max(0.0, time.time() - float(state.get("ts") or 0.0))
        except (TypeError, ValueError):
            return 1e9

    def read_events(self) -> List[Dict[str, Any]]:
        """增量读取 JSONL；文件被截断/轮换时从头重读。"""
        try:
            stat = self.events_path.stat()
        except OSError:
            return []
        inode = int(getattr(stat, "st_ino", 0) or 0)
        if inode and self._events_inode and inode != self._events_inode:
            self._events_offset = 0
        if stat.st_size < self._events_offset:
            self._events_offset = 0
        self._events_inode = inode
        out: List[Dict[str, Any]] = []
        try:
            with self.events_path.open("rb") as fh:
                fh.seek(self._events_offset)
                for raw in fh:
                    self._events_offset += len(raw)
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(item, dict) and int(item.get("version") or 0) == 1:
                        out.append(item)
        except OSError:
            return []
        return out

    # ── 写 ────────────────────────────────
    def next_id(self, prefix: str = "line") -> str:
        self._seq += 1
        return f"{prefix}-{int(time.time() * 1000)}-{self._seq}"

    def write_reply(self, text: str, *, priority: str = "P1",
                    ttl: float = 6.0, mood: str = "", line_id: str = "") -> Dict[str, Any]:
        text = " ".join(str(text or "").split()).strip()
        if len(text) > 160:
            text = text[:159] + "…"
        payload = {
            "version": 1,
            "id": line_id or self.next_id("line"),
            "ts": time.time(),
            "ttl": max(1.0, float(ttl)),
            "text": text,
            "mood": str(mood or ""),
            "priority": priority,
            "channel": "subtitle",
        }
        if text:
            write_json(self.reply_path, payload)
            line = "%s|%.6f|%.1f|%s\n" % (
                payload["id"], payload["ts"], payload["ttl"],
                text.replace("\r", " ").replace("\n", " "))
            _atomic_write(self.reply_text_path, line)
        return payload

    def write_heartbeat(self, *, game_seq: int = 0, plugin_seq: int = 0,
                        status: str = "ok") -> None:
        write_json(self.heartbeat_path, {
            "version": 1, "ts": time.time(), "game_seq": int(game_seq or 0),
            "plugin_seq": int(plugin_seq or 0), "status": status,
        })

    def read_heartbeat(self) -> Optional[Dict[str, Any]]:
        for path in (self.heartbeat_path,
                     self.heartbeat_path.with_name(self.heartbeat_path.name + ".csv")):
            data = read_json(path)
            if data is not None:
                return data
        return None

    def read_reply(self) -> Optional[Dict[str, Any]]:
        return read_json(self.reply_path)

    def consume_vision_request(self) -> bool:
        """游戏内 F11 写入的一次性视觉侦察请求。"""
        path = self.root / "vision_request.txt"
        if not path.exists():
            return False
        try:
            path.unlink()
        except OSError:
            pass
        return True

    def consume_assist_request(self) -> str:
        """Consume one F12/manual assist request and return its focus."""
        path = self.root / "assist_request.txt"
        if not path.exists():
            return ""
        focus = "brief"
        try:
            raw = path.read_text(encoding="utf-8-sig", errors="ignore").strip().lower()
            if raw in {"brief", "quest", "boss", "review"}:
                focus = raw
        except OSError:
            pass
        try:
            path.unlink()
        except OSError:
            pass
        return focus
