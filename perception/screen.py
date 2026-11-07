"""PBZ 窗口截图（只截游戏窗口，不截桌面）。

截图本身不调用任何模型；由宿主通过 push_message / @llm_tool 的图像部件
交给主程序视觉模型。这样复用宿主已有的视觉感知，不重复造轮子。
"""

from __future__ import annotations

import base64
import io
import time
from typing import Any, Dict, Optional

_LAST_CAPTURE: Dict[str, Any] = {"ts": 0.0, "ok": False, "error": "not_captured"}


def _user32():
    import ctypes
    return ctypes.windll.user32


def _titles() -> tuple[str, ...]:
    return ("Phantom Blade Zero", "影之刃零", "PBZ")


def find_pbz_window() -> Optional[int]:
    """枚举可见窗口，返回 PBZ 主窗口 HWND。"""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    user32 = _user32()
    found = [None]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            title = buf.value.strip()
            if not title or not any(k.lower() in title.lower() for k in _titles()):
                return True
            if "codex" in title.lower() or "n.e.k.o" in title.lower():
                return True
            found[0] = hwnd
            return False
        except Exception:
            return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        return None
    return found[0]


def _bbox(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    rect = wintypes.RECT()
    if not _user32().GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    if right - left < 320 or bottom - top < 240:
        return None
    return left, top, right, bottom


def _foreground(hwnd: int) -> bool:
    try:
        return int(_user32().GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def capture_pbz_window(*, require_foreground: bool = True,
                       max_edge: int = 1024, quality: int = 80) -> Dict[str, Any]:
    """截取 PBZ 窗口并压缩为 JPEG。

    Returns: {ok, image_bytes, data_b64, mime, width, height, error, captured_at}
    """
    global _LAST_CAPTURE
    started = time.time()
    result: Dict[str, Any] = {
        "ok": False, "image_bytes": b"", "data_b64": "", "mime": "image/jpeg",
        "width": 0, "height": 0, "error": "", "captured_at": started,
    }
    hwnd = find_pbz_window()
    if not hwnd:
        result["error"] = "未找到《影之刃零》窗口"
        _LAST_CAPTURE = result
        return result
    if require_foreground and not _foreground(hwnd):
        result["error"] = "游戏不在前台，请先切回游戏画面"
        _LAST_CAPTURE = result
        return result
    bbox = _bbox(hwnd)
    if bbox is None:
        result["error"] = "游戏窗口尺寸异常"
        _LAST_CAPTURE = result
        return result
    try:
        from PIL import Image, ImageGrab, ImageStat
    except ImportError:
        result["error"] = "缺少 Pillow，无法截图"
        _LAST_CAPTURE = result
        return result
    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=False)
        if img is None:
            result["error"] = "截图失败"
            _LAST_CAPTURE = result
            return result
        if img.mode != "RGB":
            img = img.convert("RGB")
        # 排除全黑截图（独占全屏/PrtSc 保护常见）
        stat = ImageStat.Stat(img.resize((32, 32)).convert("L"))
        if stat.mean and float(stat.mean[0]) < 3.0:
            result["error"] = "画面全黑，可能被独占全屏挡住"
            _LAST_CAPTURE = result
            return result
        w, h = img.size
        longest = max(w, h)
        if longest > max_edge:
            scale = max_edge / longest
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        raw = buf.getvalue()
        result.update({
            "ok": True, "image_bytes": raw,
            "data_b64": base64.b64encode(raw).decode("ascii"),
            "width": img.size[0], "height": img.size[1],
        })
    except Exception as exc:
        result["error"] = str(exc)
    _LAST_CAPTURE = result
    return result
