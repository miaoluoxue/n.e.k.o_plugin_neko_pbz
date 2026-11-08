"""Validate data files and release invariants without the host SDK."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    plugin = tomllib.loads((ROOT / "plugin.toml").read_text(encoding="utf-8"))
    if not plugin.get("plugin", {}).get("version"):
        fail("plugin.toml 缺少版本号")

    all_ids = set()
    counts = {}
    for path in sorted((ROOT / "data" / "knowledge").glob("seed*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail(f"{path.name} JSON 无法读取: {exc}")
        if not isinstance(data, dict):
            fail(f"{path.name} 顶层必须是对象")
        seen = set()
        for entity in data.get("entities") or []:
            if not isinstance(entity, dict):
                fail(f"{path.name} 存在非对象实体")
            entity_id = str(entity.get("id") or "")
            name = str(entity.get("name") or "")
            if not entity_id or not name:
                fail(f"{path.name} 存在缺少 id/name 的实体")
            if entity_id in seen:
                fail(f"{path.name} 实体 ID 重复: {entity_id}")
            seen.add(entity_id)
            all_ids.add(entity_id)
        counts[path.name] = len(data.get("entities") or [])

    i18n_root = ROOT / "i18n"
    bundles = {}
    for locale in ("zh-CN", "zh-TW", "en"):
        path = i18n_root / f"{locale}.json"
        try:
            bundles[locale] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail(f"{path.name} JSON 无法读取: {exc}")
    keys = set(bundles["zh-CN"])
    if keys != set(bundles["zh-TW"]) or keys != set(bundles["en"]):
        fail("i18n locale 键不一致")

    panel = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for hook in ('data-i18n="nav.battle"', 'data-i18n="scan.title"',
                 'data-assist-focus="brief"', 'id="diagList"'):
        if hook not in panel:
            fail(f"面板缺少关键挂载点: {hook}")

    print(json.dumps({
        "ok": True,
        "version": plugin["plugin"]["version"],
        "seed_files": counts,
        "unique_entity_ids": len(all_ids),
        "i18n_keys": len(keys),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
