"""打印 PBZ 桥接状态，用于首次进游戏后的 P0 核验。

用法:
    python scripts/probe_report.py
    python scripts/probe_report.py "E:\\...\\ProjectPBZ\\Saved\\NekoBridge"
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

DEFAULT = Path(r"E:\SteamLibrary\steamapps\common\PBZ\ProjectPBZ\Saved\NekoBridge")


def load(root: Path) -> dict:
    for name in ("state.json", "state.json.csv", "state.csv"):
        p = root / name
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8-sig"))
    raise FileNotFoundError(f"{root} 下没有 state.json；先启动游戏并确认 JS Mod 已加载")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    state = load(root)
    p = state.get("player") or {}
    eq = p.get("equipment") or {}
    caps = state.get("capabilities") or {}
    print(f"桥接目录: {root}")
    print(f"状态年龄: {time.time() - float(state.get('ts') or 0):.1f}s  seq={state.get('seq')}")
    print(f"区域: {((state.get('world') or {}).get('name') or (state.get('world') or {}).get('id') or '?')}")
    print(f"玩家: {p.get('name') or '?'}  HP={p.get('hp')}/{p.get('max_hp')} "
          f"({p.get('hp_percent')}%)  杀气={(p.get('shachi') or {}).get('percent')}%")
    print(f"战斗: in_combat={p.get('in_combat')} dead={p.get('dead')} "
          f"movement={p.get('movement')}")
    print(f"主武器: {eq.get('main_weapon')}")
    print(f"影之武装: {eq.get('phantom_edges')}")
    print(f"饰品: {eq.get('accessories')}")
    print(f"Boss: {state.get('boss')}")
    print(f"铃铛: {state.get('bell')}")
    print(f"任务数: {len(state.get('quests') or [])}")
    print(f"敌人({len(state.get('enemies') or [])}): {(state.get('enemies') or [])[:5]}")
    print("\n能力探测:")
    print(json.dumps(caps, ensure_ascii=False, indent=2))
    if not caps.get("vitals", {}).get("hp"):
        print("\n[!] 没读到生命值：需要继续找 GAS Attribute/UI 字段。")
    if not caps.get("enemy_classes"):
        print("[!] 没发现敌人/Boss 类：需要通过 UE4SS SDK/对象转储确认类名。")
    if not caps.get("equipment", {}).get("main_weapon"):
        print("[!] 没读到主武器：需要确认装备子系统字段。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
