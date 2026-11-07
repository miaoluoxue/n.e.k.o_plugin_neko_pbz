"""跨会话记忆：按存档分文件夹持久化。

data/memory/
  _global/profile.json
  <存档>/
    save.json
    bosses.json
    facts.json
    preferences.json
    promises.json
    sessions/<session>.json

不记录背包、材料数量、原始截图、键盘输入或完整聊天记录。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def resolve_save_key(state: Dict[str, Any], configured: str = "") -> str:
    if configured and str(configured).strip():
        return str(configured).strip()
    save = state.get("save") or {}
    slot = str(save.get("slot") or save.get("id") or "").strip()
    if slot:
        return f"slot:{slot}"
    player = state.get("player") or {}
    character = str(player.get("name") or save.get("character") or "player").strip()
    # 没有存档槽时不要用地图 ID 做 key：换区域会把同一档记忆拆成多份。
    return f"{character}@default"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _slug(save_key: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff@.-]+", "_", save_key).strip("._")[:42]
    digest = hashlib.sha1(save_key.encode("utf-8")).hexdigest()[:8]
    return f"{safe or 'save'}-{digest}"


class MemoryStore:
    def __init__(self, path: Path | str) -> None:
        root = Path(path)
        if root.suffix.lower() == ".db":
            root = root.parent / "memory"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "_global").mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._migrate_sqlite()

    # ── 基础路径 ─────────────────────────
    def close(self) -> None:
        """JSON 存储无需关闭文件句柄；保留接口兼容。"""
        return None

    def _dir(self, save_key: str) -> Path:
        return self.root / _slug(save_key)

    def _session_dir(self, save_key: str) -> Path:
        path = self._dir(save_key) / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_save(self, save_key: str) -> Path:
        path = self._dir(save_key)
        path.mkdir(parents=True, exist_ok=True)
        if not (path / "save.json").exists():
            now = time.time()
            _write(path / "save.json", {
                "save_key": save_key, "character_name": "", "game_version": "",
                "world_id": "", "first_seen": now, "last_seen": now,
            })
        return path

    # ── 旧 SQLite 迁移 ───────────────────
    def _migrate_sqlite(self) -> None:
        candidates = [self.root / "pbz_memory.db", self.root.parent / "pbz_memory.db"]
        db_path = next((p for p in candidates if p.exists()), None)
        if db_path is None:
            return
        try:
            db = sqlite3.connect(str(db_path))
            db.row_factory = sqlite3.Row
            tables = {r["name"] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "saves" in tables:
                for row in db.execute("SELECT * FROM saves"):
                    path = self._ensure_save(row["save_key"])
                    _write(path / "save.json", dict(row))
            if "profile" in tables:
                row = db.execute("SELECT * FROM profile WHERE id=1").fetchone()
                if row:
                    try:
                        prefs = json.loads(row["preferences_json"] or "{}")
                    except ValueError:
                        prefs = {}
                    _write(self.root / "_global" / "profile.json", {
                        "call_name": row["call_name"] or "",
                        "preferences": prefs,
                        "quiet_until": float(row["quiet_until"] or 0),
                        "updated_at": float(row["updated_at"] or 0),
                    })
            if "encounters" in tables:
                grouped: Dict[str, Dict[str, Any]] = {}
                for row in db.execute("SELECT * FROM encounters"):
                    grouped.setdefault(row["save_key"], {})[row["boss_id"]] = dict(row)
                for key, bosses in grouped.items():
                    _write(self._ensure_save(key) / "bosses.json", bosses)
            if "facts" in tables:
                grouped: Dict[str, Dict[str, Any]] = {}
                for row in db.execute("SELECT * FROM facts"):
                    fk = f"{row['kind']}:{row['key']}"
                    grouped.setdefault(row["save_key"], {})[fk] = dict(row)
                for key, facts in grouped.items():
                    _write(self._ensure_save(key) / "facts.json", facts)
            if "promises" in tables:
                grouped: Dict[str, List[Dict[str, Any]]] = {}
                for row in db.execute("SELECT * FROM promises"):
                    grouped.setdefault(row["save_key"], []).append(dict(row))
                for key, promises in grouped.items():
                    _write(self._ensure_save(key) / "promises.json", promises)
            if "sessions" in tables:
                for row in db.execute("SELECT * FROM sessions"):
                    target = self._session_dir(row["save_key"]) / f"{row['id']}.json"
                    _write(target, dict(row))
            db.close()
            try:
                os.replace(db_path, db_path.with_suffix(".db.migrated"))
            except OSError:
                pass
        except Exception:
            try:
                db.close()
            except Exception:
                pass

    # ── 档案 / 偏好 ──────────────────────
    def touch_save(self, save_key: str, *, character_name: str = "",
                   game_version: str = "", world_id: str = "") -> None:
        now = time.time()
        with self._lock:
            path = self._ensure_save(save_key)
            data = _read(path / "save.json", {})
            data.update({
                "save_key": save_key, "character_name": character_name,
                "game_version": game_version, "world_id": world_id,
                "first_seen": data.get("first_seen", now), "last_seen": now,
            })
            _write(path / "save.json", data)

    def get_profile(self) -> Dict[str, Any]:
        with self._lock:
            data = _read(self.root / "_global" / "profile.json", {})
        return {
            "call_name": data.get("call_name", ""),
            "preferences": data.get("preferences") or {},
            "quiet_until": float(data.get("quiet_until") or 0),
        }

    def set_preferences(self, patch: Dict[str, Any], *, call_name: str = "",
                        save_key: str = "") -> Dict[str, Any]:
        with self._lock:
            profile = self.get_profile()
            prefs = dict(profile.get("preferences") or {})
            prefs.update(patch or {})
            profile.update({
                "call_name": call_name or profile.get("call_name") or "",
                "preferences": prefs,
                "quiet_until": float(prefs.get("quiet_until") or profile.get("quiet_until") or 0),
                "updated_at": time.time(),
            })
            _write(self.root / "_global" / "profile.json", profile)
            if save_key:
                path = self._ensure_save(save_key)
                local = _read(path / "preferences.json", {})
                local.update(prefs)
                _write(path / "preferences.json", local)
            return profile

    # ── 事件 ─────────────────────────────
    def record_event(self, save_key: str, event: Dict[str, Any],
                     *, current_boss: Optional[Dict[str, Any]] = None) -> None:
        kind = str(event.get("type") or "")
        data = event.get("data") or {}
        boss = current_boss or {}
        boss_id = str(boss.get("id") or boss.get("name") or data.get("boss_id") or "")
        boss_name = str(boss.get("name") or data.get("name") or "")
        now = float(event.get("ts") or time.time())
        with self._lock:
            path = self._ensure_save(save_key)
            bosses = _read(path / "bosses.json", {})
            if kind == "boss_spawn" and boss_id:
                row = bosses.get(boss_id) or {
                    "boss_id": boss_id, "boss_name": boss_name, "attempts": 0,
                    "deaths": 0, "best_hp_percent": None, "first_kill_at": None,
                    "last_result": "", "last_ts": 0,
                }
                row["boss_name"] = boss_name or row.get("boss_name", "")
                row["attempts"] = int(row.get("attempts", 0)) + 1
                row["last_ts"] = now
                bosses[boss_id] = row
            elif kind in ("low_hp", "boss_phase") and boss_id:
                row = bosses.get(boss_id)
                hp = data.get("hp_percent")
                if row and hp is not None:
                    old = row.get("best_hp_percent")
                    row["best_hp_percent"] = float(hp) if old is None else min(float(old), float(hp))
                    row["last_ts"] = now
            elif kind == "death" and boss_id:
                row = bosses.get(boss_id)
                if row:
                    row["deaths"] = int(row.get("deaths", 0)) + 1
                    row["last_result"] = "death"
                    row["last_ts"] = now
            elif kind == "victory" and boss_id:
                row = bosses.get(boss_id) or {
                    "boss_id": boss_id, "boss_name": boss_name, "attempts": 1,
                    "deaths": 0, "best_hp_percent": 0,
                }
                row["first_kill_at"] = row.get("first_kill_at") or now
                row["last_result"] = "victory"
                row["last_ts"] = now
                bosses[boss_id] = row
            if bosses:
                _write(path / "bosses.json", bosses)

            facts = _read(path / "facts.json", {})
            fact = None
            if kind == "bell_activated":
                fact = ("bell", str(data.get("bell_id") or ""), str(data.get("name") or ""))
            elif kind == "zone_change":
                fact = ("zone", "current", str(data.get("name") or data.get("world_id") or ""))
            elif kind == "weapon_changed":
                w = data.get("weapon") or {}
                fact = ("weapon", "current",
                        f"{w.get('name','')}|{w.get('id','')}|{w.get('tier','')}")
            elif kind == "quest_progress":
                fact = ("quest", str(data.get("quest") or ""), str(data.get("progress") or ""))
            if fact:
                fk = f"{fact[0]}:{fact[1]}"
                old = facts.get(fk) or {
                    "kind": fact[0], "key": fact[1], "first_seen": now,
                    "confidence": 1, "source": "runtime",
                }
                old.update({"value": fact[2], "last_seen": now})
                facts[fk] = old
                _write(path / "facts.json", facts)

    # ── 会话 ─────────────────────────────
    def start_session(self, save_key: str) -> str:
        session_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        with self._lock:
            self._session_dir(save_key)
            _write(self._session_dir(save_key) / f"{session_id}.json", {
                "id": session_id, "save_key": save_key,
                "started_at": time.time(), "ended_at": None,
                "summary": "", "mood_end": "",
            })
        return session_id

    def end_session(self, session_id: Any, summary: str = "", mood_end: str = "") -> None:
        if not session_id:
            return
        with self._lock:
            for path in self.root.glob("*/sessions/*.json"):
                data = _read(path, {})
                if str(data.get("id")) == str(session_id):
                    data.update({"ended_at": time.time(), "summary": summary,
                                 "mood_end": mood_end})
                    _write(path, data)
                    return

    # ── 约定 ─────────────────────────────
    def add_promise(self, save_key: str, text: str, due_hint: str = "") -> int:
        with self._lock:
            path = self._ensure_save(save_key)
            promises = _read(path / "promises.json", [])
            pid = max([int(p.get("id", 0)) for p in promises] or [0]) + 1
            promises.append({"id": pid, "text": text, "due_hint": due_hint,
                             "status": "open", "created_at": time.time()})
            _write(path / "promises.json", promises)
            return pid

    def close_promise(self, promise_id: int) -> None:
        with self._lock:
            for path in self.root.glob("*/promises.json"):
                promises = _read(path, [])
                changed = False
                for item in promises:
                    if int(item.get("id", -1)) == int(promise_id):
                        item["status"] = "done"
                        changed = True
                if changed:
                    _write(path, promises)
                    return

    def open_promises(self, save_key: str, limit: int = 5) -> List[Dict[str, Any]]:
        with self._lock:
            promises = _read(self._dir(save_key) / "promises.json", [])
        return [p for p in promises if p.get("status") == "open"][-limit:]

    # ── 查询 ─────────────────────────────
    def boss_history(self, save_key: str, limit: int = 8) -> List[Dict[str, Any]]:
        with self._lock:
            bosses = _read(self._dir(save_key) / "bosses.json", {})
        return sorted(bosses.values(), key=lambda x: x.get("last_ts", 0), reverse=True)[:limit]

    def digest(self, save_key: str, limit: int = 8) -> str:
        lines: List[str] = []
        with self._lock:
            sessions = []
            for path in self._session_dir(save_key).glob("*.json"):
                data = _read(path, {})
                if data.get("summary"):
                    sessions.append(data)
            sessions.sort(key=lambda x: x.get("started_at", 0), reverse=True)
            if sessions:
                lines.append(f"上次：{sessions[0]['summary']}")
            for b in self.boss_history(save_key, 3):
                bits = [f"尝试 {b.get('attempts', 0)} 次"]
                if b.get("deaths"):
                    bits.append(f"死亡 {b['deaths']} 次")
                if b.get("best_hp_percent") is not None:
                    bits.append(f"最好打到 {float(b['best_hp_percent']):.0f}%")
                if b.get("first_kill_at"):
                    bits.append("已击杀")
                lines.append(f"Boss {b.get('boss_name') or b.get('boss_id')}：" + "，".join(bits))
            facts = _read(self._dir(save_key) / "facts.json", {})
            for f in sorted(facts.values(), key=lambda x: x.get("last_seen", 0), reverse=True)[:6]:
                if f.get("kind") == "zone":
                    lines.append(f"最近区域：{f.get('value')}")
                elif f.get("kind") == "weapon":
                    lines.append(f"最近武器：{str(f.get('value', '')).split('|')[0]}")
            for p in self.open_promises(save_key, 3):
                lines.append(f"约定：{p.get('text')}")
        return "\n".join(f"- {x}" for x in lines[:limit])

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            saves = [p for p in self.root.iterdir()
                     if p.is_dir() and not p.name.startswith("_")
                     and p.name not in ("exports", "archive")]
            encounters = sessions = promises = 0
            for path in saves:
                encounters += len(_read(path / "bosses.json", {}))
                sessions += len(list((path / "sessions").glob("*.json"))) if (path / "sessions").exists() else 0
                promises += sum(1 for p in _read(path / "promises.json", [])
                                if p.get("status") == "open")
            return {"saves": len(saves), "encounters": encounters,
                    "sessions": sessions, "promises": promises}

    def clear(self, save_key: str = "") -> None:
        with self._lock:
            if save_key:
                target = self._dir(save_key)
                if target.exists() and target.parent == self.root:
                    shutil.rmtree(target)
            else:
                for path in self.root.iterdir():
                    if path.is_dir() and not path.name.startswith("_") \
                            and path.name not in ("exports", "archive"):
                        shutil.rmtree(path)
                profile = self.root / "_global" / "profile.json"
                if profile.exists():
                    profile.unlink()

    def export(self, save_key: str) -> Dict[str, Any]:
        base = self._dir(save_key)
        out: Dict[str, Any] = {}
        for name in ("save.json", "bosses.json", "facts.json",
                     "preferences.json", "promises.json"):
            out[name] = _read(base / name, {})
        sessions = []
        for path in (base / "sessions").glob("*.json"):
            sessions.append(_read(path, {}))
        out["sessions"] = sorted(sessions, key=lambda x: x.get("started_at", 0))
        return out
