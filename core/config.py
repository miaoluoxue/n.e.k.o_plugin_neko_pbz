"""插件配置：默认值、用户覆盖、桥接目录探测。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable

from .secrets import protect_secret, unprotect_secret

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "bridge_dir": "",
    "game_install_dir": "",
    "poll_interval": 0.35,
    "state_stale_seconds": 4.0,
    "save_key": "",
    "spoiler_level": 1,
    "verbosity": "normal",
    "voice_enabled": True,
    "overlay_enabled": True,
    "proactive": True,
    "show_prompt_in_chat": False,
    "event_chat_hold_seconds": 20.0,
    "boss_advice_min": 1,
    "boss_advice_max": 3,
    "host_reply_timeout": 10.0,
    "quiet_until": 0.0,
    "memory_retention_days": 90,
    "knowledge_path": "",
    "event_log_limit": 200,
    # 独立 LLM：复用 neko_arcade 的客户端；只做记忆摘要/知识整理，
    # 猫娘最终台词仍由宿主 LLM + TTS 负责。
    "llm_enabled": False,
    "llm_provider": "openai_compatible",
    "llm_model": "",
    "llm_api_key": "",
    "llm_base_url": "",
    "llm_timeout": 20.0,
    "llm_max_calls_per_minute": 10,
    # 画面感知：复用宿主视觉模型，不自己造视觉模型。
    "vision_enabled": True,
    "vision_require_foreground": True,
    "vision_max_edge": 1024,
    "vision_jpeg_quality": 80,
    "vision_cooldown": 8.0,
    # 游戏内 F12 / 面板快捷互动：交给宿主当前人设即时回应。
    "assist_enabled": True,
    "assist_cooldown": 3.0,
    # 面板偏好：持久化到 data/config/ui.json
    "ui_style": "scroll",
    "ui_theme": "ink",
    "ui_density": "comfortable",
    "ui_scale": 100,
    "ui_motion": True,
    "ui_show_radar": True,
    "ui_show_llm_strip": True,
}

def public_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """返回可安全交给面板/命令响应的配置副本，永不回传 API Key。"""
    out = dict(cfg)
    out["llm_key_set"] = bool(str(out.get("llm_api_key") or "").strip())
    out["llm_api_key"] = ""
    return out


# 兼容扩展位；默认桥接目录由 %LOCALAPPDATA%、用户配置和文档目录动态解析。
_BRIDGE_CANDIDATES = ()


def _home_documents() -> Iterable[Path]:
    home = Path.home()
    yield home / "Documents" / "PbzMods" / "NekoBridge"
    yield home / "OneDrive" / "Documents" / "PbzMods" / "NekoBridge"


def _bridge_activity(path: Path) -> float:
    """Latest game-written bridge file; ignore plugin-only heartbeat."""
    candidates = [
        path / "state" / "New_CSV.csv",
        path / "state.json",
        path / "state.csv",
        path / "mod_status" / "New_CSV.csv",
        path / "mod_status.json",
        path / "game_heartbeat" / "New_CSV.csv",
    ]
    latest = 0.0
    for candidate in candidates:
        try:
            latest = max(latest, candidate.stat().st_mtime)
        except OSError:
            pass
    return latest


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def bridge_candidates(configured: str = "") -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path).casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if str(local):
        add(local / "ProjectPBZ" / "Saved" / "NekoBridge")
    if configured and str(configured).strip():
        add(Path(str(configured)).expanduser())
    for raw in _BRIDGE_CANDIDATES:
        add(Path(raw))
    for path in _home_documents():
        add(path)
    return out


def _ensure_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return _exists(path)


def resolve_bridge_dir(
    configured: str = "",
    fallback_root: Path | str | None = None,
) -> Path:
    """找到游戏 Mod 与插件共用的桥接目录。

    游戏侧用 `ProjectSavedDir()/NekoBridge`，所以优先带活动文件的路径；
    找不到时退回插件可写数据目录，避免首次启动被用户目录权限卡死。
    """
    candidates = bridge_candidates(configured)
    active = [(path, _bridge_activity(path)) for path in candidates]
    fresh = [(path, stamp) for path, stamp in active if stamp > 0]
    if fresh:
        path = max(fresh, key=lambda item: item[1])[0]
        _ensure_directory(path)
        return path
    configured_path = next(
        (path for path in candidates if configured and str(path) == str(Path(configured))),
        None,
    )
    if configured_path is not None and _ensure_directory(configured_path):
        return configured_path
    for path in candidates:
        if _exists(path.parent) and _ensure_directory(path):
            return path
    fallback = (Path(fallback_root) if fallback_root is not None
                else Path.home() / "NekoBridge")
    _ensure_directory(fallback)
    return fallback


def _read(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class ConfigStore:
    """分层持久化配置，全部位于插件 data/config 下。

    data/config/general.json  游戏/陪玩/桥接
    data/config/llm.json      独立 LLM（Key 只在本机）
    data/config/ui.json       面板主题/密度/动效
    """

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)
        self.config_dir = self.data_root / "config"
        self.general_path = self.config_dir / "general.json"
        self.llm_path = self.config_dir / "llm.json"
        self.ui_path = self.config_dir / "ui.json"
        self.legacy_path = self.config_dir / "user.json"

    def _category(self, key: str) -> str:
        if key.startswith("llm_"):
            return "llm"
        if key.startswith("ui_"):
            return "ui"
        return "general"

    def load(self) -> Dict[str, Any]:
        cfg = dict(DEFAULTS)
        for path in (self.general_path, self.llm_path, self.ui_path):
            raw = _read(path)
            for key, value in raw.items():
                if key in DEFAULTS and value is not None:
                    cfg[key] = value
            if path == self.llm_path and raw.get("llm_api_key_enc"):
                try:
                    cfg["llm_api_key"] = unprotect_secret(
                        str(raw["llm_api_key_enc"]))
                except (OSError, ValueError):
                    cfg["llm_api_key"] = ""
        legacy = _read(self.legacy_path)
        if legacy:
            for key, value in legacy.items():
                if key in DEFAULTS and value is not None:
                    cfg[key] = value
            self._migrate_legacy(cfg)
        cfg["bridge_dir"] = str(resolve_bridge_dir(
            str(cfg.get("bridge_dir") or ""),
            self.data_root / "bridge",
        ))
        return cfg

    def _migrate_legacy(self, cfg: Dict[str, Any]) -> None:
        """把旧的 user.json 拆成 general/llm/ui，保留原文件备份。"""
        try:
            self._write_category_files(cfg)
            backup = self.legacy_path.with_name("user.json.legacy.bak")
            if not backup.exists():
                os.replace(self.legacy_path, backup)
        except OSError:
            pass

    def _write_category_files(self, cfg: Dict[str, Any]) -> None:
        buckets: Dict[str, Dict[str, Any]] = {"general": {}, "llm": {}, "ui": {}}
        for key in DEFAULTS:
            value = cfg.get(key, DEFAULTS[key])
            if key == "llm_api_key":
                value = ""
            buckets[self._category(key)][key] = value
        protected_key = protect_secret(str(cfg.get("llm_api_key") or ""))
        if protected_key:
            buckets["llm"]["llm_api_key_enc"] = protected_key
        _write(self.general_path, buckets["general"])
        _write(self.llm_path, buckets["llm"])
        _write(self.ui_path, buckets["ui"])

    def save(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.load()
        for key, value in (patch or {}).items():
            if key in DEFAULTS and value is not None:
                cfg[key] = value
        cfg["bridge_dir"] = str(resolve_bridge_dir(
            str(cfg.get("bridge_dir") or ""),
            self.data_root / "bridge",
        ))
        self._write_category_files(cfg)
        return cfg

    def paths(self) -> Dict[str, str]:
        return {
            "config_dir": str(self.config_dir),
            "general": str(self.general_path),
            "llm": str(self.llm_path),
            "ui": str(self.ui_path),
        }
