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
import stat
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List

APP_ID = "4115450"
GAME_DIR_NAME = "PBZ"
MOD_ID = "pbz-neko-companion"
OWN_JS_SOURCE = Path("ProjectPBZ/PBZModLoader/mods/pbz-neko-companion")
OWN_JS_GENERATED = Path("ProjectPBZ/Content/JavaScript/PBZModLoader/generated-mods/"
                        "pbz-neko-companion")
OWN_MODS_INI = Path("ProjectPBZ/PBZModLoader/mods.ini")
OWN_LUA = Path("platform/steam/ue4ss/Mods/PBZNekoCompanion")
RUNTIME_MANIFEST = Path("game_bundle/runtime-manifest.json")
MAX_RUNTIME_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_RUNTIME_EXPANDED_BYTES = 128 * 1024 * 1024


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


def _download_runtime_archive(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "neko_pbz-runtime-installer/1"}
    )
    total = 0
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_RUNTIME_ARCHIVE_BYTES:
                    raise GameInstallError("UE4SS 运行时下载文件过大")
                handle.write(chunk)


def _extract_runtime_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    expanded = 0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise GameInstallError("UE4SS 运行时压缩包包含不安全路径")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise GameInstallError("UE4SS 运行时压缩包不能包含符号链接")
            expanded += info.file_size
            if expanded > MAX_RUNTIME_EXPANDED_BYTES:
                raise GameInstallError("UE4SS 运行时解压后体积过大")
            target = (destination / member).resolve()
            if not target.is_relative_to(root):
                raise GameInstallError("UE4SS 运行时压缩包路径越界")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


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
        self.runtime = self.plugin_root / "game_bundle" / "runtime"
        self.runtime_manifest = self.plugin_root / RUNTIME_MANIFEST
        self.js_source = (
            self.plugin_root / "game_bundle" / "mod" / "js"
            / "pbz-neko-companion"
        )
        self.lua_source = (
            self.plugin_root / "game_bundle" / "mod" / "lua"
            / "PBZNekoCompanion"
        )
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

    def _load_runtime_manifest(self) -> Dict[str, Any]:
        try:
            manifest = json.loads(
                self.runtime_manifest.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise GameInstallError(f"无法读取 UE4SS 运行时清单：{exc}") from exc
        url = str(manifest.get("url") or "")
        digest = str(manifest.get("sha256") or "").upper()
        size = manifest.get("size")
        if not url.startswith("https://"):
            raise GameInstallError("UE4SS 运行时下载地址必须使用 HTTPS")
        if re.fullmatch(r"[0-9A-F]{64}", digest) is None:
            raise GameInstallError("UE4SS 运行时清单 SHA-256 无效")
        if not isinstance(size, int) or not 0 < size <= MAX_RUNTIME_ARCHIVE_BYTES:
            raise GameInstallError("UE4SS 运行时清单文件大小无效")
        return {**manifest, "url": url, "sha256": digest, "size": size}

    def _local_runtime_ready(self) -> bool:
        return all(path.is_file() for path in (
            self.runtime / "dwmapi.dll",
            self.runtime / "version.dll",
            self.runtime / "ue4ss" / "UE4SS.dll",
        ))

    def _runtime_ready(self) -> tuple[bool, str]:
        try:
            self._load_runtime_manifest()
        except GameInstallError as exc:
            return False, str(exc)
        if self.runtime.exists() and not self._local_runtime_ready():
            return False, f"本地 UE4SS 运行时目录不完整：{self.runtime}"
        missing = [
            str(path)
            for path in (
                self.js_source / "main.js",
                self.js_source / "game_api.js",
                self.lua_source / "Scripts" / "main.lua",
            )
            if not path.is_file()
        ]
        return not missing, ", ".join(missing)

    @contextmanager
    def _runtime_source(self) -> Iterator[Path]:
        if self._local_runtime_ready():
            yield self.runtime
            return
        manifest = self._load_runtime_manifest()
        with tempfile.TemporaryDirectory(prefix="neko_pbz_runtime_") as temp:
            archive = Path(temp) / "runtime.zip"
            _download_runtime_archive(manifest["url"], archive)
            if archive.stat().st_size != manifest["size"]:
                raise GameInstallError("UE4SS 运行时文件大小与清单不一致")
            if _sha256(archive) != manifest["sha256"]:
                raise GameInstallError("UE4SS 运行时 SHA-256 校验失败")
            extracted = Path(temp) / "runtime"
            _extract_runtime_archive(archive, extracted)
            required = (
                extracted / "dwmapi.dll",
                extracted / "version.dll",
                extracted / "ue4ss" / "UE4SS.dll",
            )
            missing = [str(path) for path in required if not path.is_file()]
            if missing:
                raise GameInstallError(
                    "UE4SS 运行时缺少必要文件：" + ", ".join(missing)
                )
            yield extracted

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
        vendor_ok, vendor_error = self._runtime_ready()
        mod_state = self._mods_ini_state(root / OWN_MODS_INI) if root else {
            "present": False, "enabled": False,
        }
        result = {
            "ok": bool(recommended),
            "game_root": recommended,
            "configured_root": selected or self.configured_root,
            "candidates": roots[:20],
            "game_running": self.game_running(),
            "vendor_ready": vendor_ok,
            "vendor_error": vendor_error,
            "runtime_local": self._local_runtime_ready(),
            "ue4ss_present": bool(root and (
                root / "platform" / "steam" / "ue4ss" / "UE4SS.dll"
            ).is_file()),
            "mod_installed": bool(root and (
                root / OWN_JS_SOURCE / "main.js"
            ).is_file() and (
                root / OWN_LUA / "Scripts" / "main.lua"
            ).is_file()),
            "mod_enabled": mod_state["enabled"],
            "mods_ini_present": mod_state["present"],
            "generated_mod_present": bool(root and (
                root / OWN_JS_GENERATED / "main.js"
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
        entry = (f'{{"id":"{MOD_ID}","enabled":true,'
                 f'"entry":"mods/{MOD_ID}/main.js"}}')
        if not path.exists():
            path.write_text(
                "'use strict';\nmodule.exports = "
                '{"version":1,"mods":[' + entry + "]};\n",
                encoding="utf-8",
            )
            return
        text = path.read_text(encoding="utf-8-sig")
        if re.search(
                rf'"id"\s*:\s*"{re.escape(MOD_ID)}"', text):
            return
        match = re.search(r'(?s)"mods"\s*:\s*\[(?P<body>.*?)\]', text)
        if not match:
            raise GameInstallError(
                "无法安全合并 PBZModLoader generated-config.js")
        separator = "," if match.group("body").strip() else ""
        insert_at = match.end() - 1
        updated = text[:insert_at] + separator + entry + text[insert_at:]
        path.write_text(updated, encoding="utf-8")

    @staticmethod
    def _mods_ini_state(path: Path) -> Dict[str, bool]:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            return {"present": False, "enabled": False}
        section = ""
        enabled = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith((";", "#")):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().casefold()
                continue
            if section != "mods" or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().casefold() == MOD_ID:
                enabled = value.strip() == "1"
        return {"present": True, "enabled": enabled}

    @staticmethod
    def _ensure_mods_ini(path: Path) -> None:
        """持久启用源码 Mod；PBZModLoader 启动时会据此重生成 derived 文件。"""
        text = path.read_text(encoding="utf-8-sig", errors="ignore") if path.exists() else ""
        lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        section_start = -1
        section_end = len(lines)
        for index, raw in enumerate(lines):
            if raw.strip().casefold() == "[mods]":
                section_start = index
                break
        if section_start >= 0:
            for index in range(section_start + 1, len(lines)):
                line = lines[index].strip()
                if line.startswith("[") and line.endswith("]"):
                    section_end = index
                    break

        updated: List[str] = []
        found = False
        for index, raw in enumerate(lines):
            line = raw.strip()
            in_mods = section_start >= 0 and section_start < index < section_end
            if in_mods and line and not line.startswith((";", "#")) and "=" in line:
                key = line.split("=", 1)[0].strip()
                if key.casefold() == MOD_ID:
                    if not found:
                        updated.append(f"{MOD_ID}=1")
                        found = True
                    continue
            updated.append(raw)

        if section_start < 0:
            if updated and updated[-1].strip():
                updated.append("")
            updated.extend(["[Mods]", f"{MOD_ID}=1"])
        elif not found:
            updated.insert(section_start + 1, f"{MOD_ID}=1")

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(updated).rstrip() + "\n",
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)

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
            vendor_ok, vendor_error = self._runtime_ready()
            if not vendor_ok:
                raise GameInstallError(
                    "插件包内游戏侧文件不完整：" + vendor_error)

            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup_root = game_root / "_neko_pbz_backup" / stamp
            backups: List[str] = []
            tracked = (
                OWN_JS_SOURCE,
                OWN_JS_GENERATED,
                OWN_MODS_INI,
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
                with self._runtime_source() as runtime_source:
                    if ue4ss_dir.exists() and any(ue4ss_dir.iterdir()):
                        raise GameInstallError(
                            "检测到不完整的 UE4SS 目录，未覆盖现有文件")
                    for proxy in ("dwmapi.dll", "version.dll"):
                        source = runtime_source / proxy
                        target = steam_dir / proxy
                        if target.exists() and _sha256(source) != _sha256(target):
                            raise GameInstallError(
                                f"现有 {proxy} 与运行时版本不同，"
                                "为保护其他 Mod 已停止安装")
                    self._copy_tree(runtime_source / "ue4ss", ue4ss_dir)
                    for proxy in ("dwmapi.dll", "version.dll"):
                        source = runtime_source / proxy
                        target = steam_dir / proxy
                        if not target.exists():
                            shutil.copy2(source, target)

            js_target = game_root / OWN_JS_GENERATED
            source_target = game_root / OWN_JS_SOURCE
            lua_target = game_root / OWN_LUA
            self._copy_tree(self.js_source, js_target)
            self._copy_tree(self.js_source, source_target)
            self._copy_tree(self.lua_source, lua_target)
            (lua_target / "enabled.txt").write_text("1\n", encoding="ascii")

            self._ensure_mods_ini(game_root / OWN_MODS_INI)
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
                "js_source": str(OWN_JS_SOURCE),
                "js_generated": str(OWN_JS_GENERATED),
                "mods_ini": str(OWN_MODS_INI),
                "mod_enabled": self._mods_ini_state(
                    game_root / OWN_MODS_INI)["enabled"],
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
