"""Tìm cửa sổ giả lập trên màn hình — để cửa sổ ở đâu, to nhỏ thế nào cũng chạy.

Vị trí được dò LẠI ở mỗi lần click, nên kéo cửa sổ đi giữa chừng vẫn không sao.
"""

from __future__ import annotations

import platform
from typing import NamedTuple

IS_MAC = platform.system() == "Darwin"


class WindowRect(NamedTuple):
    left: int
    top: int
    width: int
    height: int
    pid: int = 0

    @property
    def area(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


class WindowNotFound(Exception):
    """Không tìm thấy cửa sổ giả lập — chưa mở, hoặc sai tên trong config."""


def _find_mac(title: str) -> WindowRect | None:
    import Quartz

    wl = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    needle = title.lower()
    best = None
    for w in wl:
        owner = (w.get("kCGWindowOwnerName") or "").lower()
        name = (w.get("kCGWindowName") or "").lower()
        if needle not in owner and needle not in name:
            continue
        b = w.get("kCGWindowBounds") or {}
        if b.get("Width", 0) < 200 or b.get("Height", 0) < 200:
            continue  # bỏ qua cửa sổ phụ, tooltip, thanh công cụ
        rect = WindowRect(
            int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"]),
            int(w.get("kCGWindowOwnerPID", 0)),
        )
        if best is None or rect.width * rect.height > best.width * best.height:
            best = rect  # cửa sổ lớn nhất khớp tên = cửa sổ chính
    return best


def _find_windows(title: str) -> WindowRect | None:
    import pygetwindow

    matches = [
        w for w in pygetwindow.getAllWindows()
        if title.lower() in (w.title or "").lower() and w.width > 200 and w.height > 200
    ]
    if not matches:
        return None
    w = max(matches, key=lambda w: w.width * w.height)
    return WindowRect(w.left, w.top, w.width, w.height)


def find_window(title: str = "BlueStacks") -> WindowRect:
    """Cửa sổ giả lập đang mở. Ném WindowNotFound nếu không thấy."""
    rect = _find_mac(title) if IS_MAC else _find_windows(title)
    if rect is None:
        raise WindowNotFound(
            f"No window found whose title contains '{title}'. Start the emulator, "
            f"or fix capture.window_title in the config."
        )
    return rect


def focus_window(title: str = "BlueStacks") -> bool:
    """Đưa cửa sổ giả lập lên trước.

    Không có bước này thì click đầu tiên bị macOS nuốt để focus cửa sổ, và tool
    phải chờ hết step_timeout mới biết mà bấm lại — mất ~15 giây mỗi lượt.
    Hàm này KHÔNG đụng tới chuột, chỉ đổi cửa sổ đang hoạt động.
    """
    try:
        if IS_MAC:
            import subprocess

            win = find_window(title)
            script = (
                f'tell application "System Events" to set frontmost of '
                f"(first process whose unix id is {win.pid}) to true"
            )
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5, check=True)
        else:
            import pygetwindow

            matches = [w for w in pygetwindow.getAllWindows() if title.lower() in (w.title or "").lower()]
            if not matches:
                return False
            max(matches, key=lambda w: w.width * w.height).activate()
        return True
    except Exception:
        return False  # không focus được thì vẫn chạy, chỉ chậm hơn


def game_rect(win: WindowRect, screen_w: int, screen_h: int) -> tuple[float, float, float, float]:
    """Vùng game bên trong cửa sổ, suy từ tỉ lệ màn hình Android.

    Giả định: game chiếm trọn bề ngang cửa sổ và nằm sát đáy — phần thừa phía trên
    là thanh tiêu đề. Đúng với BlueStacks Air; trả về (left, top, width, height)
    theo toạ độ màn hình, dạng số thực để không dồn sai số làm lệch click.
    """
    gw = float(win.width)
    gh = gw * screen_h / screen_w
    return float(win.left), win.top + (win.height - gh), gw, gh


def title_bar_height(win: WindowRect, screen_w: int, screen_h: int) -> float:
    return win.height - win.width * screen_h / screen_w
