from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "i18n"


def _load(name: str) -> dict:
    return json.loads((I18N / name).read_text(encoding="utf-8"))


def test_locale_bundles_have_same_keys():
    zh = _load("zh-CN.json")
    en = _load("en.json")
    tw = _load("zh-TW.json")
    assert zh.keys() == en.keys() == tw.keys()
    required = {
        "plugin.name", "panel.title", "nav.battle", "nav.scan",
        "scan.title", "scan.auto_refresh", "equipment.title",
        "knowledge.title", "llm.title", "settings.title",
    }
    assert required <= set(zh)
    assert all(zh[k].strip() and en[k].strip() for k in required)


def test_panel_exposes_i18n_hooks():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-i18n="nav.scan"' in html
    assert 'data-i18n="scan.title"' in html
    assert "callEntry('get_panel_state'" in html
