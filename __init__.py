"""neko_pbz：影之刃零猫娘陪玩。

职责边界：
- 游戏内 Mod：只读事实 + 字幕显示；
- 本插件：场景/事件、知识库、跨会话记忆、Boss 建议；
- 宿主：当前猫娘人设、LLM 回复与 TTS。

插件不生成固定台词，不读取背包，不修改游戏存档。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from plugin.sdk.plugin import NekoPluginBase, neko_plugin

from .entries import LifecycleMixin, ToolMixin, UiMixin


@neko_plugin
class NekoPbzPlugin(NekoPluginBase, LifecycleMixin, UiMixin, ToolMixin):
    """影之刃零陪玩插件。"""

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self.logger = self.enable_file_logging(log_level="INFO")
        self.cfg: Dict[str, Any] = {}
        self.service: Any = None
        self._boot_task: Optional[Any] = None
        self._boot_failed = False
        self._last_user_chat_at = 0.0
