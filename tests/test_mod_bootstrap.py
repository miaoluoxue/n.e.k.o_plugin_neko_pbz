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
    assert 'bridge + "/" + slot' in main
    assert 'writeFile("game_heartbeat"' in main
    assert "const ENABLE_OVERLAY = false" in main
    assert "safeMode: true" in main
    assert "SAMPLE_INTERVAL_MS = 1000" in main


def test_equipment_reads_confirmed_backpack_loadout_fields():
    api = (MOD / "game_api.js").read_text(encoding="utf-8")
    for field in (
        "CurrentMainWeaponID", "MainWeapons", "ShaqiWeapons",
        "CurrentShaqiWeaponIndex", "AssemblyAccessory",
        "TopMedicineID", "BottomMedicineID",
    ):
        assert field in api
    assert "GetMainWeaponTableData" in api
    assert "GetShaqiWeaponTableData" in api
    assert "GetAccessoryData" in api
    assert "GetMedicineData" in api
    assert "MainWeaponInfos" in api
    assert "ShaqiWeaponInfos" in api
    assert "WeaponLevel" in api
    assert "ShaChiWeaponLevel" in api
    assert "Inventories" not in api
