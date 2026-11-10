"""Game-side installer bundled with the N.E.K.O plugin.

The installer never hard-codes a drive letter. It discovers Steam libraries
from the Windows registry and ``libraryfolders.vdf``, then validates the PBZ
layout before writing anything. Existing UE4SS and third-party Mods are kept.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

APP_ID = "4115450"
GAME_DIR_NAME = "PBZ"
OWN_JS = Path("ProjectPBZ/Content/JavaScript/PBZModLoader/generated-mods/"
              "pbz-neko-companion")
OWN_JS_LEGACY = Path("ProjectPBZ/PBZModLoader/mods/pbz-neko-companion")
OWN_LUA = Path("platform/steam/ue4ss/Mods/PBZNekoCompanion")


class GameInstallError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _dedupe(paths: Iterable[tuple[Path, str]]) -> List[tuple[Path, str]]:
    out: List[tuple[Path, str]] = []
    seen: set[str] = set()
    for path, source in paths:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append((path, source))
    return out


class GameInstaller:
    def __init__(self, plugin_root: Path | str, data_root: Path | str,
                 configured_root: str = "", bridge_root: str = "") -> None:
        self.plugin_root = Path(plugin_root)
        self.data_root = Path(data_root)
        self.configured_root = str(configured_root or "").strip()
        self.bridge_root = (
            Path(bridge_root) if str(bridge_root or "").strip()
            else Path(os.environ.get("LOCALAPPDATA", ""))
            / "ProjectPBZ" / "Saved" / "NekoBridge"
        )
        self.vendor = self.plugin_root / "installer" / "vendor" / "ue4ss"
        self.js_source = self.plugin_root / "mod" / "pbz-neko-companion"
        self.lua_source = self.plugin_root / "mod" / "lua" / "PBZNekoCompanion"
        self._lock = threading.Lock()
        self._status_cache: tuple[float, str, Dict[str, Any]] | None = None

    @staticmethod
    def _valid_root(path: Path) -> bool:
        return (
            (path / "platform" / "steam" / "PBZ.exe").is_file()
            and (path / "ProjectPBZ" / "Content" / "JavaScript"
                 / "PBZModLoader").is_dir()
        )

    def normalize_root(self, raw: str) -> Path | None:
        text = str(raw or "").strip().strip('"')
        if not text:
            return None
        candidate = Path(text).expanduser()
        try:
            candidate = candidate.resolve()
        except OSError:
            return None
        for current in (candidate, candidate.parent, candidate.parent.parent):
            if self._valid_root(current):
                return current
        return None

    @staticmethod
    def _steam_roots() -> List[Path]:
        roots: List[Path] = []
        try:
            import winreg

            locations = (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"Software\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"Software\Valve\Steam", "InstallPath"),
            )
            for hive, key_name, value_name in locations:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    if value:
                        roots.append(Path(str(value)))
                except OSError:
                    continue
        except ImportError:
            pass

        for env_name in ("STEAM_PATH", "PROGRAMFILES(X86)", "PROGRAMFILES"):
            value = os.environ.get(env_name, "").strip()
            if value:
                roots.append(Path(value) / "Steam" if "PROGRAM" in env_name
                             else Path(value))
        return roots

    def _steam_libraries(self, steam_root: Path) -> List[Path]:
        libraries = [steam_root]
        for path in (
            steam_root / "steamapps" / "libraryfolders.vdf",
            steam_root / "config" / "libraryfolders.vdf",
        ):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in re.finditer(r'"path"\s*"([^"]+)"', text,
                                     flags=re.IGNORECASE):
                libraries.append(Path(match.group(1).replace("\\\\", "\\")))
        return libraries

    def _disk_candidates(self) -> List[Path]:
        out: List[Path] = []
        try:
            import ctypes

            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for index in range(26):
                if not (mask & (1 << index)):
                    continue
                root = Path(chr(ord("A") + index) + ":\\")
                for relative in (
                    Path("SteamLibrary/steamapps/common") / GAME_DIR_NAME,
                    Path("Steam/steamapps/common") / GAME_DIR_NAME,
                    Path("Games/SteamLibrary/steamapps/common") / GAME_DIR_NAME,
                ):
                    out.append(root / relative)
        except (AttributeError, OSError):
            pass
        return out

    def discover_roots(self, selected: str = "") -> List[Dict[str, Any]]:
        candidates: List[tuple[Path, str]] = []
        for raw, source in (
            (selected, "selected"),
            (self.configured_root, "saved"),
        ):
            normalized = self.normalize_root(raw)
            if normalized:
                candidates.append((normalized, source))

        for steam_root in self._steam_roots():
            for library in self._steam_libraries(steam_root):
                candidates.append((
                    library / "steamapps" / "common" / GAME_DIR_NAME,
                    "steam-library",
                ))
        for path in self._disk_candidates():
            candidates.append((path, "disk-layout"))

        results = []
        for path, source in _dedupe(candidates):
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            results.append({
                "path": str(resolved),
                "source": source,
                "valid": self._valid_root(resolved),
            })
        return results

    @staticmethod
    def game_running() -> bool:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq PBZ.exe", "/NH"],
                capture_output=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return b"PBZ.exe" in result.stdout.lower()
        except (OSError, subprocess.SubprocessError):
            return False

    def _vendor_ready(self) -> tuple[bool, str]:
        required = (
            self.vendor / "dwmapi.dll",
            self.vendor / "version.dll",
            self.vendor / "ue4ss" / "UE4SS.dll",
            self.js_source / "main.js",
            self.js_source / "game_api.js",
            self.lua_source / "Scripts" / "main.lua",
        )
        missing = [str(path) for path in required if not path.is_file()]
        return not missing, ", ".join(missing)

    def status(self, selected: str = "") -> Dict[str, Any]:
        cache_key = str(selected or self.configured_root or "")
        now = time.time()
        if (self._status_cache
                and self._status_cache[1] == cache_key
                and now - self._status_cache[0] < 5.0):
            return dict(self._status_cache[2])
        roots = self.discover_roots(selected)
        valid = [item for item in roots if item["valid"]]
        recommended = valid[0]["path"] if valid else ""
        root = Path(recommended) if recommended else None
        vendor_ok, vendor_error = self._vendor_ready()
        result = {
            "ok": bool(recommended),
            "game_root": recommended,
            "configured_root": selected or self.configured_root,
            "candidates": roots[:20],
            "game_running": self.game_running(),
            "vendor_ready": vendor_ok,
            "vendor_error": vendor_error,
            "ue4ss_present": bool(root and (
                root / "platform" / "steam" / "ue4ss" / "UE4SS.dll"
            ).is_file()),
            "mod_installed": bool(root and (
                root / OWN_JS / "main.js"
            ).is_file() and (
                root / OWN_LUA / "Scripts" / "main.lua"
            ).is_file()),
            "can_install": bool(root and vendor_ok and not self.game_running()),
            "error": "" if recommended else "未找到影之刃零安装目录",
        }
        self._status_cache = (now, cache_key, result)
        return dict(result)

    def _backup(self, game_root: Path, backup_root: Path,
                relative: Path) -> None:
        source = game_root / relative
        if not source.exists():
            return
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)

    @staticmethod
    def _copy_tree(source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(source):
            current = destination / Path(root).relative_to(source)
            current.mkdir(parents=True, exist_ok=True)
            for name in files:
                shutil.copy2(Path(root) / name, current / name)

    def _ensure_js_config(self, path: Path) -> None:
        entry = ('{"id":"pbz-neko-companion","enabled":true,'
                 '"entry":"mods/pbz-neko-companion/main.js"}')
        if not path.exists():
            path.write_text(
                "'use strict';\nmodule.exports = "
                '{"version":1,"mods":[' + entry + "]};\n",
                encoding="utf-8",
            )
            return
        text = path.read_text(encoding="utf-8-sig")
        if re.search(
                r'"id"\s*:\s*"pbz-neko-companion"', text):
            return
        match = re.search(r'(?s)"mods"\s*:\s*\[(?P<body>.*?)\]', text)
        if not match:
            raise GameInstallError(
                "无法安全合并 PBZModLoader generated-config.js")
        separator = "," if match.group("body").strip() else ""
        insert_at = match.end() - 1
        updated = text[:insert_at] + separator + entry + text[insert_at:]
        path.write_text(updated, encoding="utf-8")

    def _ensure_mods_txt(self, path: Path) -> None:
        text = path.read_text(
            encoding="utf-8", errors="ignore") if path.exists() else ""
        if re.search(r"(?m)^\s*PBZNekoCompanion\s*:", text):
            return
        prefix = "" if not text or text.endswith("\n") else "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="ascii", newline="\n") as handle:
            handle.write(prefix + "PBZNekoCompanion : 1\n")

    def install(self, selected: str = "") -> Dict[str, Any]:
        with self._lock:
            roots = self.discover_roots(selected)
            valid = [item for item in roots if item["valid"]]
            if not valid:
                raise GameInstallError(
                    "未找到《影之刃零》游戏目录，请在面板中填写游戏根目录")
            game_root = Path(valid[0]["path"])
            if self.game_running():
                raise GameInstallError("请先关闭《影之刃零》再安装游戏侧组件")
            vendor_ok, vendor_error = self._vendor_ready()
            if not vendor_ok:
                raise GameInstallError(
                    "插件包内游戏侧文件不完整：" + vendor_error)

            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup_root = game_root / "_neko_pbz_backup" / stamp
            backups: List[str] = []
            tracked = (
                OWN_JS,
                OWN_JS_LEGACY,
                OWN_LUA,
                Path("ProjectPBZ/Content/JavaScript/PBZModLoader/"
                     "generated-config.js"),
                Path("platform/steam/ue4ss/Mods/mods.txt"),
            )
            for relative in tracked:
                self._backup(game_root, backup_root, relative)
                if (game_root / relative).exists():
                    backups.append(str(relative))

            steam_dir = game_root / "platform" / "steam"
            ue4ss_dir = steam_dir / "ue4ss"
            ue4ss_present = (ue4ss_dir / "UE4SS.dll").is_file()
            if not ue4ss_present:
                if ue4ss_dir.exists() and any(ue4ss_dir.iterdir()):
                    raise GameInstallError(
                        "检测到不完整的 UE4SS 目录，未覆盖现有文件")
                for proxy in ("dwmapi.dll", "version.dll"):
                    source = self.vendor / proxy
                    target = steam_dir / proxy
                    if target.exists() and _sha256(source) != _sha256(target):
                        raise GameInstallError(
                            f"现有 {proxy} 与插件内置版本不同，"
                            "为保护其他 Mod 已停止安装")
                self._copy_tree(self.vendor / "ue4ss", ue4ss_dir)
                for proxy in ("dwmapi.dll", "version.dll"):
                    source = self.vendor / proxy
                    target = steam_dir / proxy
                    if not target.exists():
                        shutil.copy2(source, target)

            js_target = game_root / OWN_JS
            legacy_target = game_root / OWN_JS_LEGACY
            lua_target = game_root / OWN_LUA
            self._copy_tree(self.js_source, js_target)
            self._copy_tree(self.js_source, legacy_target)
            self._copy_tree(self.lua_source, lua_target)
            (lua_target / "enabled.txt").write_text("1\n", encoding="ascii")

            self._ensure_js_config(
                game_root / "ProjectPBZ/Content/JavaScript/PBZModLoader/"
                "generated-config.js")
            self._ensure_mods_txt(
                game_root / "platform/steam/ue4ss/Mods/mods.txt")

            for slot in ("state", "mod_status", "game_heartbeat"):
                (self.bridge_root / slot).mkdir(parents=True, exist_ok=True)

            state = {
                "installed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                               time.gmtime()),
                "game_root": str(game_root),
                "ue4ss_preserved": ue4ss_present,
                "backups": backups,
                "backup_root": str(backup_root),
            }
            backup_root.mkdir(parents=True, exist_ok=True)
            (backup_root / "install-state.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._status_cache = None
            return {"ok": True, **state}
