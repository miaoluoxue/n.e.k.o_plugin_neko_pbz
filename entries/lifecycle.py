"""启动/停止与后台服务调度。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from plugin.sdk.plugin import lifecycle

from ..core.config import ConfigStore
from ..core.service import PbzService


class LifecycleMixin:
    cfg: Dict[str, Any]
    service: Any
    _boot_task: Any
    _boot_failed: bool

    def _data_root(self) -> Path:
        try:
            return Path(self.data_path())
        except Exception:
            return Path(__file__).resolve().parent.parent / "data"

    @lifecycle(id="startup")
    async def pbz_startup(self, **_) -> None:
        try:
            if (self.config_dir / "static").exists():
                self.register_static_ui(
                    "static", index_file="index.html",
                    cache_control="no-cache, no-store, must-revalidate")
        except Exception as exc:
            self.logger.warning("注册静态面板失败: %s", exc)
        try:
            self.set_list_actions([{
                "id": "open_ui",
                "label": "打开陪玩面板",
                "kind": "ui",
                "target": f"/plugin/{self.plugin_id}/ui/",
                "open_in": "new_tab",
            }])
        except Exception:
            pass

    async def _on_command_loop_start(self) -> None:
        """宿主持久命令循环上启动后台服务。"""
        task = getattr(self, "_boot_task", None)
        if task is not None and not task.done():
            return
        self._boot_task = asyncio.create_task(self._pbz_boot())

    async def _pbz_boot(self) -> None:
        self._boot_failed = False
        try:
            data_root = self._data_root()
            store = ConfigStore(data_root)
            self.cfg = store.load()
            if not self.cfg.get("enabled", True):
                self.logger.info("neko_pbz 已禁用")
                return
            self.service = PbzService(self, self.cfg, data_root)
            await self.service.start()
            self.logger.info("neko_pbz 服务已启动，桥接目录: %s", self.cfg["bridge_dir"])
        except Exception as exc:
            self._boot_failed = True
            self.logger.exception("neko_pbz 启动失败: %s", exc)

    @lifecycle(id="shutdown")
    async def pbz_shutdown(self, **_) -> None:
        task = getattr(self, "_boot_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self.service:
            await self.service.stop()
        self.logger.info("neko_pbz 已停止")
