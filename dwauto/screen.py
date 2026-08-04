"""Chụp màn hình + nhận diện nút bằng template matching.

Hai tầng tách biệt để test được không cần màn hình:
  - hàm thuần (`find_template`, `image_to_mouse`) chỉ nhận/trả numpy array + số;
  - lớp `Screen` bọc `mss` cho phần thật sự cần màn hình.

Toạ độ: mọi thứ trong module này là **pixel của ảnh chụp**. Trên Retina (macOS) hay
Windows DPI scaling >100%, pixel ảnh ≠ toạ độ chuột — đổi bằng `Screen.to_mouse()`
trước khi đưa cho `actions.click()`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import NamedTuple

import cv2
import mss
import numpy as np

DEFAULT_THRESHOLD = 0.85

# mss >= 10 đổi tên mss.mss() thành mss.MSS(); giữ tương thích cả hai.
_MSS = getattr(mss, "MSS", None) or mss.mss

Region = tuple[int, int, int, int]  # (x1, y1, x2, y2) trong toạ độ pixel của ảnh


class Match(NamedTuple):
    """Kết quả khớp template. `x, y` là **tâm** vùng khớp, tính theo pixel ảnh."""

    x: int
    y: int
    score: float
    left: int
    top: int
    width: int
    height: int


_template_cache: dict[tuple[str, float, int], np.ndarray] = {}


def load_template(path: str | Path) -> np.ndarray:
    """Đọc ảnh mẫu (BGR), có cache theo mtime+size để không đọc lại mỗi vòng lặp."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError as exc:
        raise FileNotFoundError(f"Không tìm thấy template: {p}") from exc

    key = (str(p.resolve()), st.st_mtime, st.st_size)
    img = _template_cache.get(key)
    if img is None:
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Không đọc được ảnh template: {p}")
        _template_cache.clear()  # chỉ giữ bản mới nhất của mỗi file
        _template_cache[key] = img
    return img


def _as_bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img


def find_template(
    screen: np.ndarray,
    template: str | Path | np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    region: Region | None = None,
) -> Match | None:
    """Tìm `template` trong `screen` bằng cv2.matchTemplate (TM_CCOEFF_NORMED).

    Trả `Match` với tâm tính theo toạ độ ảnh gốc (đã cộng offset của `region`),
    hoặc `None` nếu điểm khớp cao nhất < `threshold`.
    """
    tpl = _as_bgr(template if isinstance(template, np.ndarray) else load_template(template))
    haystack = _as_bgr(screen)

    off_x = off_y = 0
    if region is not None:
        x1, y1, x2, y2 = region
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(haystack.shape[1], x2), min(haystack.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            return None
        haystack = haystack[y1:y2, x1:x2]
        off_x, off_y = x1, y1

    th, tw = tpl.shape[:2]
    hh, hw = haystack.shape[:2]
    if th == 0 or tw == 0 or th > hh or tw > hw:
        # cv2.matchTemplate ném lỗi nếu template lớn hơn vùng tìm → coi như không thấy.
        return None

    res = cv2.matchTemplate(haystack, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val < threshold:
        return None

    left, top = max_loc[0] + off_x, max_loc[1] + off_y
    return Match(
        x=left + tw // 2,
        y=top + th // 2,
        score=float(max_val),
        left=left,
        top=top,
        width=tw,
        height=th,
    )


def image_to_mouse(
    x: int,
    y: int,
    area: dict[str, int],
    scale: tuple[float, float],
) -> tuple[int, int]:
    """Đổi pixel trong ảnh chụp → toạ độ chuột (logic) để pyautogui click đúng chỗ."""
    return (
        round(area["left"] + x / scale[0]),
        round(area["top"] + y / scale[1]),
    )


class Screen:
    """Bọc mss: chụp một vùng cố định và tự đo tỉ lệ scale của màn hình."""

    def __init__(
        self,
        area: dict[str, int] | None = None,
        monitor_index: int = 1,
        scale: tuple[float, float] = (1.0, 1.0),
    ):
        self.monitor_index = monitor_index
        self._area = area
        self.scale = scale  # đo lại ở mỗi lần capture()
        self._sct = None

    @property
    def sct(self):
        if self._sct is None:
            self._sct = _MSS()
        return self._sct

    @property
    def area(self) -> dict[str, int]:
        if self._area is None:
            mon = self.sct.monitors[self.monitor_index]
            self._area = {k: mon[k] for k in ("left", "top", "width", "height")}
        return self._area

    def capture(self) -> np.ndarray:
        """Ảnh BGR của vùng theo dõi; cập nhật `self.scale` theo kích thước thật."""
        area = self.area
        shot = self.sct.grab(area)
        frame = cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)
        self.scale = (frame.shape[1] / area["width"], frame.shape[0] / area["height"])
        return frame

    def find(
        self,
        template: str | Path | np.ndarray,
        threshold: float = DEFAULT_THRESHOLD,
        region: Region | None = None,
        screen: np.ndarray | None = None,
    ) -> Match | None:
        """Chụp (hoặc dùng ảnh cho sẵn) rồi tìm template."""
        img = self.capture() if screen is None else screen
        return find_template(img, template, threshold, region)

    def wait_for(
        self,
        template: str | Path | np.ndarray,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: float = DEFAULT_THRESHOLD,
        region: Region | None = None,
    ) -> Match | None:
        """Poll đến khi thấy template hoặc hết giờ. Luôn thử ít nhất một lần."""
        deadline = time.monotonic() + timeout
        while True:
            match = self.find(template, threshold, region)
            if match is not None:
                return match
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def to_mouse(self, x: int, y: int) -> tuple[int, int]:
        """Pixel ảnh → toạ độ chuột, dùng scale đo được ở lần capture gần nhất."""
        return image_to_mouse(x, y, self.area, self.scale)

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    def __enter__(self) -> Screen:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
