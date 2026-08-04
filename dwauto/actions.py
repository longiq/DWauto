"""Giả lập chuột qua pyautogui — chỉ input, không đụng vào game.

`dry_run=True` thì chỉ ghi log "sẽ click ở (x,y)" và không đụng gì tới chuột thật,
dùng để kiểm tra nhận diện nút trước khi cho chạy thật.
"""

from __future__ import annotations

import logging
import random
import time

log = logging.getLogger(__name__)


class Mouse:
    def __init__(
        self,
        offset_px: int = 4,
        delay: tuple[float, float] = (0.35, 0.9),
        move_duration: tuple[float, float] = (0.08, 0.2),
        dry_run: bool = False,
        rng: random.Random | None = None,
    ):
        self.offset_px = offset_px
        self.delay = delay
        self.move_duration = move_duration
        self.dry_run = dry_run
        self.rng = rng or random.Random()
        self._pyautogui = None

    @property
    def pyautogui(self):
        # Import trễ: dry-run và test chạy được ở nơi không có màn hình.
        if self._pyautogui is None:
            import pyautogui

            pyautogui.FAILSAFE = True  # kéo chuột lên góc trên-trái để dừng khẩn cấp
            self._pyautogui = pyautogui
        return self._pyautogui

    def jitter(self, x: int, y: int) -> tuple[int, int]:
        """Lệch ngẫu nhiên quanh tâm nút để không click trùng một pixel mãi."""
        if self.offset_px <= 0:
            return x, y
        return (
            x + self.rng.randint(-self.offset_px, self.offset_px),
            y + self.rng.randint(-self.offset_px, self.offset_px),
        )

    def click(self, x: int, y: int, label: str = "") -> tuple[int, int]:
        """Click tại (x, y) — TOẠ ĐỘ CHUỘT, không phải pixel ảnh chụp."""
        cx, cy = self.jitter(x, y)
        tag = f" [{label}]" if label else ""
        if self.dry_run:
            log.info("DRY-RUN: would click at (%d, %d)%s", cx, cy, tag)
            return cx, cy

        log.info("click (%d, %d)%s", cx, cy, tag)
        pag = self.pyautogui
        pag.moveTo(cx, cy, duration=self.rng.uniform(*self.move_duration))
        pag.click()
        self.sleep(self.rng.uniform(*self.delay))
        return cx, cy

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
