from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "mod" / "pbz-neko-companion"


def test_overlay_failure_cannot_block_state_sampling():
    main = (MOD / "main.js").read_text(encoding="utf-8")
    overlay = (MOD / "ui_bridge.js").read_text(encoding="utf-8")
    assert 'writeFile("state.json"' in main
    assert "if (overlay) overlay.tick();" in main
    assert 'writeFile("mod_status.json"' in main
    assert "this.ready = false" in overlay
    assert "subtitle AddWidget failed" in overlay
    assert "lastCreateAttempt" in overlay
