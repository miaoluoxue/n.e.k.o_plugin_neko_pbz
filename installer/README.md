# Bundled game runtime

`installer/vendor/ue4ss` and `mod/` are runtime resources shipped inside the
N.E.K.O plugin package.

Do not publish them as a separate game ZIP. The panel entry
`pbz_install_game_mod` detects the PBZ installation and installs only this
plugin's files while preserving existing UE4SS and third-party Mods.

Refresh the pinned UE4SS snapshot after verifying a new game build:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\sync_vendor_ue4ss.ps1
```
