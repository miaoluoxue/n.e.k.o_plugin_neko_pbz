"""游戏知识库：实体、关系、Boss 建议池。

原则：
- 只从已验证来源给具体建议；
- 不足 1~3 条就给实际数量，不补编；
- 不读玩家背包，只根据当前装备与 Boss 类型做加权。
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  aliases TEXT DEFAULT '',
  region TEXT DEFAULT '',
  spoiler_level INTEGER DEFAULT 1,
  confidence REAL DEFAULT 0.5,
  source TEXT DEFAULT '',
  facts_json TEXT DEFAULT '{}',
  updated_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS relations (
  src TEXT NOT NULL,
  rel TEXT NOT NULL,
  dst TEXT NOT NULL,
  meta_json TEXT DEFAULT '{}',
  PRIMARY KEY (src, rel, dst)
);
CREATE TABLE IF NOT EXISTS tips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  boss_id TEXT NOT NULL,
  text TEXT NOT NULL,
  tags TEXT DEFAULT '',
  spoiler_level INTEGER DEFAULT 1,
  weight REAL DEFAULT 1,
  verified INTEGER DEFAULT 0,
  source TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_tips_boss ON tips(boss_id, verified);
"""


def _split(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


class KnowledgeStore:
    def __init__(self, db_path: Path | str, seed_path: Path | str | None = None,
                 corrections_dir: Path | str | None = None) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.corrections_dir = Path(corrections_dir) if corrections_dir else None
        if self.corrections_dir:
            self.corrections_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.executescript(_SCHEMA)
            self.db.commit()
        if seed_path:
            self.load_seed(seed_path)

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def load_seed(self, path: Path | str) -> int:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        count = 0
        now = time.time()
        with self._lock:
            for e in raw.get("entities") or []:
                if not e.get("id") or not e.get("name"):
                    continue
                self.db.execute(
                    """INSERT INTO entities(id,type,name,aliases,region,spoiler_level,
                                            confidence,source,facts_json,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         type=excluded.type, name=excluded.name, aliases=excluded.aliases,
                         region=excluded.region, spoiler_level=excluded.spoiler_level,
                         confidence=excluded.confidence, source=excluded.source,
                         facts_json=excluded.facts_json, updated_at=excluded.updated_at""",
                    (e["id"], e.get("type", ""), e["name"],
                     json.dumps(_split(e.get("aliases")), ensure_ascii=False),
                     e.get("region", ""), int(e.get("spoiler_level", 1)),
                     float(e.get("confidence", 0.5)), e.get("source", ""),
                     json.dumps(e.get("facts") or {}, ensure_ascii=False), now),
                )
                count += 1
            for r in raw.get("relations") or []:
                if not (r.get("src") and r.get("rel") and r.get("dst")):
                    continue
                self.db.execute(
                    """INSERT OR REPLACE INTO relations(src,rel,dst,meta_json)
                       VALUES(?,?,?,?)""",
                    (r["src"], r["rel"], r["dst"],
                     json.dumps(r.get("meta") or {}, ensure_ascii=False)),
                )
            for t in raw.get("tips") or []:
                if not t.get("boss_id") or not t.get("text"):
                    continue
                exists = self.db.execute(
                    "SELECT 1 FROM tips WHERE boss_id=? AND text=? LIMIT 1",
                    (t["boss_id"], t["text"]),
                ).fetchone()
                if not exists:
                    self.db.execute(
                        """INSERT INTO tips(boss_id,text,tags,spoiler_level,weight,verified,source)
                           VALUES(?,?,?,?,?,?,?)""",
                        (t["boss_id"], t["text"], ",".join(_split(t.get("tags"))),
                         int(t.get("spoiler_level", 1)), float(t.get("weight", 1)),
                         1 if t.get("verified") else 0, t.get("source", "")),
                    )
            self.db.commit()
        return count

    def apply_corrections(self) -> int:
        """Reapply player corrections after versioned seeds have been refreshed."""
        if not self.corrections_dir or not self.corrections_dir.exists():
            return 0
        applied = 0
        with self._lock:
            for path in sorted(self.corrections_dir.glob("*.json")):
                try:
                    items = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    entity_id = str(item.get("entity_id") or "").strip()
                    field = str(item.get("field") or "").strip()
                    if not entity_id or not field or "value" not in item:
                        continue
                    entity = self.get(entity_id, spoiler_level=99)
                    if not entity:
                        continue
                    facts = dict(entity.get("facts") or {})
                    evidence = dict(facts.get("_evidence") or {})
                    facts[field] = item["value"]
                    evidence.update({
                        "status": "player_verified",
                        "source": str(item.get("source") or "player"),
                        "verified_at": float(item.get("ts") or time.time()),
                        "note": str(item.get("note") or evidence.get("note") or ""),
                        "before_value": item.get("before_value"),
                    })
                    history = list(evidence.get("history") or [])
                    history.append({
                        "field": field,
                        "value": item["value"],
                        "before_value": item.get("before_value"),
                        "source": str(item.get("source") or "player"),
                        "ts": float(item.get("ts") or time.time()),
                    })
                    evidence["history"] = history[-12:]
                    facts["_evidence"] = evidence
                    self.db.execute(
                        """UPDATE entities SET facts_json=?, confidence=1, source=?, updated_at=?
                           WHERE id=?""",
                        (json.dumps(facts, ensure_ascii=False),
                         str(item.get("source") or "player"), time.time(),
                         entity.get("id") or entity_id),
                    )
                    applied += 1
            self.db.commit()
        return applied

    # ── 查询 ─────────────────────────────
    @staticmethod
    def _row(row: sqlite3.Row) -> Dict[str, Any]:
        out = dict(row)
        try:
            out["aliases"] = json.loads(out.get("aliases") or "[]")
        except ValueError:
            out["aliases"] = []
        try:
            out["facts"] = json.loads(out.get("facts_json") or "{}")
        except ValueError:
            out["facts"] = {}
        out.pop("facts_json", None)
        return out

    def get(self, key: str, *, spoiler_level: int = 1) -> Optional[Dict[str, Any]]:
        key = str(key or "").strip()
        if not key:
            return None
        with self._lock:
            row = self.db.execute(
                "SELECT * FROM entities WHERE id=?", (key,)).fetchone()
            if not row:
                row = self.db.execute(
                    "SELECT * FROM entities WHERE name=? LIMIT 1", (key,)).fetchone()
            if not row:
                rows = self.db.execute("SELECT * FROM entities").fetchall()
                for item in rows:
                    try:
                        aliases = json.loads(item["aliases"] or "[]")
                    except ValueError:
                        aliases = []
                    if key in aliases:
                        row = item
                        break
        if not row:
            return None
        out = self._row(row)
        if int(out.get("spoiler_level") or 1) > spoiler_level:
            out["facts"] = {}
            out["hidden_by_spoiler"] = True
        return out

    def search(self, query: str = "", *, limit: int = 8,
               spoiler_level: int = 1, type: str = "") -> List[Dict[str, Any]]:
        q = str(query or "").strip()
        kind = str(type or "").strip()
        if not q and not kind:
            return []
        like = f"%{q}%"
        with self._lock:
            if kind:
                rows = self.db.execute(
                    """SELECT * FROM entities
                       WHERE type=? AND (name LIKE ? OR aliases LIKE ? OR facts_json LIKE ?)
                       ORDER BY CASE WHEN name=? THEN 0 ELSE 1 END, name LIMIT ?""",
                    (kind, like, like, like, q, limit),
                ).fetchall()
            else:
                rows = self.db.execute(
                    """SELECT * FROM entities
                       WHERE name LIKE ? OR aliases LIKE ? OR facts_json LIKE ?
                       ORDER BY CASE WHEN name=? THEN 0 ELSE 1 END, name LIMIT ?""",
                    (like, like, like, q, limit),
                ).fetchall()
        out = []
        for r in rows:
            item = self._row(r)
            if int(item.get("spoiler_level") or 1) > spoiler_level:
                item["facts"] = {}
                item["hidden_by_spoiler"] = True
            out.append(item)
        return out

    def relations(self, entity_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM relations WHERE src=? OR dst=?", (entity_id, entity_id)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Boss 建议 ────────────────────────
    def select_tips(self, boss: Dict[str, Any], equipped: Dict[str, Any],
                    *, spoiler_level: int = 1, k_min: int = 1, k_max: int = 3,
                    rng: Optional[random.Random] = None) -> List[str]:
        rng = rng or random.Random()
        boss_id = str(boss.get("id") or boss.get("name") or "")
        boss_name = str(boss.get("name") or "")
        with self._lock:
            rows = self.db.execute(
                """SELECT * FROM tips
                   WHERE verified=1 AND spoiler_level<=?
                     AND (boss_id=? OR boss_id=? OR boss_id='boss.generic')""",
                (spoiler_level, boss_id, boss_name),
            ).fetchall()
        if not rows:
            return []
        types = set()
        for edge in equipped.get("phantom_edges") or []:
            if isinstance(edge, dict):
                types.update(_split(edge.get("type")) + _split(edge.get("tags")))
        weapon = equipped.get("main_weapon") or {}
        types.update(_split(weapon.get("type")) + _split(weapon.get("tags")))
        pool = []
        for r in rows:
            tags = set(_split(r["tags"]))
            bonus = 1.0
            needs = {t.split(":", 1)[1] for t in tags if t.startswith("needs:")}
            if needs & types:
                bonus += 1.2
            pool.append((max(0.1, float(r["weight"]) * bonus), r["text"]))
        want = rng.randint(max(0, k_min), max(k_min, k_max))
        chosen: List[str] = []
        for _ in range(min(want, len(pool))):
            total = sum(w for w, _ in pool)
            pick = rng.random() * total
            acc = 0.0
            for i, (weight, text) in enumerate(pool):
                acc += weight
                if pick <= acc:
                    chosen.append(text)
                    pool.pop(i)
                    break
        return chosen

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            corrections = self.list_corrections(limit=100000)
            return {
                "entities": self.db.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"],
                "relations": self.db.execute("SELECT COUNT(*) c FROM relations").fetchone()["c"],
                "tips": self.db.execute("SELECT COUNT(*) c FROM tips WHERE verified=1").fetchone()["c"],
                "unverified_tips": self.db.execute(
                    "SELECT COUNT(*) c FROM tips WHERE verified=0").fetchone()["c"],
                "corrections": len(corrections),
                "player_verified": len({
                    str(item.get("entity_id") or "") for item in corrections
                    if item.get("entity_id")
                }),
            }

    def coverage(self) -> Dict[str, int]:
        with self._lock:
            rows = self.db.execute(
                "SELECT type, COUNT(*) c FROM entities GROUP BY type ORDER BY type"
            ).fetchall()
        return {str(r["type"]): int(r["c"]) for r in rows}

    def remember_correction(self, entity_id: str, field: str, value: Any,
                            *, source: str = "player", note: str = "") -> bool:
        if not self.corrections_dir or not entity_id:
            return False
        field = str(field or "").strip()
        if not field or field.startswith("_") or len(field) > 80:
            return False
        applied = False
        with self._lock:
            entity = self.get(entity_id, spoiler_level=99)
            if entity:
                facts = dict(entity.get("facts") or {})
                before = facts.get(field)
                evidence = dict(facts.get("_evidence") or {})
                now = time.time()
                history = list(evidence.get("history") or [])
                history.append({
                    "field": field,
                    "value": value,
                    "before_value": before,
                    "source": source,
                    "ts": now,
                })
                evidence.update({
                    "status": "player_verified",
                    "source": source,
                    "verified_at": now,
                    "note": str(note or ""),
                    "before_value": before,
                    "history": history[-12:],
                })
                facts[field] = value
                facts["_evidence"] = evidence
                self.db.execute(
                    """UPDATE entities SET facts_json=?, confidence=1, source=?, updated_at=?
                       WHERE id=?""",
                    (json.dumps(facts, ensure_ascii=False), source, now,
                     entity.get("id") or entity_id),
                )
                self.db.commit()
                applied = True
        if not applied:
            return False
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", entity_id)[:80] or "entity"
        path = self.corrections_dir / f"{safe}.json"
        with self._lock:
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(items, list):
                    items = []
            except (OSError, ValueError):
                items = []
            items.append({
                "entity_id": entity_id, "field": field, "value": value,
                "before_value": before, "note": note, "source": source,
                "ts": time.time(),
            })
            path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        return True

    def list_corrections(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.corrections_dir or not self.corrections_dir.exists():
            return []
        items: List[Dict[str, Any]] = []
        for path in sorted(self.corrections_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(raw, list):
                items.extend(item for item in raw if isinstance(item, dict))
        items.sort(key=lambda item: float(item.get("ts") or 0), reverse=True)
        return items[:max(0, int(limit))]
