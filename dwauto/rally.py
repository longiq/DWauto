"""State machine chu trình rally.

Luồng thật đo được từ recordings_mac (04/08/2026) — 4 click, không có bước chọn team:

    world map ──search_button──▶ panel Rally ──search_confirm──▶ popup mục tiêu
              ──rally_button──▶ panel March ──march_button──▶ world map

Mỗi bước đều **kiểm chứng được**: template của màn hình kế tiếp phải hiện ra sau
click, nếu không thì click lại. Nhờ vậy tool chịu được click bị macOS nuốt (khi
BlueStacks chưa được focus, click đầu tiên chỉ để focus cửa sổ — đã gặp lúc ghi),
animation chậm, và click trượt.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, NamedTuple

log = logging.getLogger(__name__)


class Step(NamedTuple):
    name: str
    template: str  # nút cần click (cũng là dấu hiệu "đang ở đúng màn hình")
    expect: str | None  # template phải hiện sau click; None = chờ nút vừa bấm biến mất


STEPS = (
    Step("search", "search_button", "search_confirm"),
    Step("confirm", "search_confirm", "rally_button"),
    Step("rally", "rally_button", "march_button"),
    # Bấm March xong game chạy animation bay tới điểm tập kết, world map chưa hiện
    # ngay. Dấu hiệu đáng tin là panel March đóng lại, không phải map xuất hiện.
    Step("march", "march_button", None),
)

# Hỏng liên tiếp bấy nhiêu lượt thì bỏ vòng, chờ tới vòng sau. Không có chặn này thì
# game kẹt ở world map (hết lượt march, hết quân...) sẽ bị click liên tục vô ích.
MAX_CONSECUTIVE_FAILURES = 2


class RallyRunner:
    def __init__(
        self,
        screen,
        mouse,
        cfg,
        should_stop: Callable[[], bool] | None = None,
        focus: Callable[[], bool] | None = None,
    ):
        self.screen = screen
        self.mouse = mouse
        self.cfg = cfg
        self.should_stop = should_stop or (lambda: False)
        self.focus = focus or (lambda: True)
        self.marches_done = 0
        self.marches_failed = 0

    # ---------- tiện ích ----------

    def _tpl(self, name: str) -> str:
        return str(self.cfg.templates[name])

    def _wait(self, name: str, timeout: float | None = None):
        return self.screen.wait_for(
            self._tpl(name),
            timeout=self.cfg.step_timeout if timeout is None else timeout,
            interval=self.cfg.poll_interval,
            threshold=self.cfg.threshold_for(name),
        )

    def _find(self, name: str):
        return self.screen.find(self._tpl(name), threshold=self.cfg.threshold_for(name))

    def _wait_gone(self, name: str) -> bool:
        """Chờ tới khi nút biến mất — dùng cho bước cuối, xem như click đã ăn."""
        deadline = time.monotonic() + self.cfg.step_timeout
        while True:
            if self._find(name) is None:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.cfg.poll_interval)

    def _reached(self, step: Step) -> bool:
        if step.expect is None:
            return self._wait_gone(step.template)
        return self._wait(step.expect) is not None

    def sleep(self, seconds: float) -> bool:
        """Nghỉ nhưng vẫn phản hồi lệnh dừng. Trả False nếu bị yêu cầu dừng."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.should_stop():
                return False
            time.sleep(min(0.25, deadline - time.monotonic()))
        return not self.should_stop()

    # ---------- một bước ----------

    def do_step(self, step: Step) -> bool:
        match = self._wait(step.template)
        if match is None:
            log.warning("[%s] %s not found - skipping this march", step.name, step.template)
            return False

        for attempt in range(self.cfg.retries + 1):
            mx, my = self.screen.to_mouse(match.x, match.y)
            self.mouse.click(mx, my, label=f"{step.name}/{step.template}")

            if self._reached(step):
                return True

            if attempt < self.cfg.retries:
                log.warning(
                    "[%s] clicked but did not reach %s (attempt %d/%d) - retrying",
                    step.name, step.expect or f"{step.template} disappearing",
                    attempt + 1, self.cfg.retries,
                )
                if self.should_stop():
                    return False
                again = self._find(step.template)
                if again is None:
                    # Nút biến mất mà màn hình kế cũng chưa hiện → đang chuyển cảnh.
                    log.warning("[%s] %s vanished too - waiting for the transition", step.name, step.template)
                    return self._reached(step)
                match = again

        log.error("[%s] failed after %d clicks", step.name, self.cfg.retries + 1)
        return False

    # ---------- một lượt march ----------

    def march_once(self) -> bool:
        if not self.focus():
            log.debug("Could not raise the emulator window - the first click may be swallowed")
        for step in STEPS:
            if self.should_stop():
                return False
            if not self.do_step(step):
                self.marches_failed += 1
                return False
        self.marches_done += 1
        log.info("March done (%d succeeded / %d failed)", self.marches_done, self.marches_failed)
        return True

    def recover(self) -> bool:
        """Sau một lượt hỏng: chờ quay lại được world map thì mới đi tiếp."""
        log.info("Looking for the world map...")
        if self._wait("search_button", timeout=self.cfg.step_timeout * 2) is not None:
            return True
        log.error("Cannot find the world map - check the game and emulator window")
        return False

    # ---------- một vòng ----------

    def run_round(self) -> int:
        """Chạy `marches_per_round` lượt liên tiếp. Trả số lượt thành công."""
        ok = 0
        consecutive_fail = 0
        for i in range(self.cfg.marches_per_round):
            if self.should_stop():
                break
            log.info("--- March %d/%d ---", i + 1, self.cfg.marches_per_round)
            if self.march_once():
                ok += 1
                consecutive_fail = 0
                continue

            consecutive_fail += 1
            if consecutive_fail >= MAX_CONSECUTIVE_FAILURES:
                log.error("%d marches failed in a row - skipping to the next cycle", consecutive_fail)
                break
            if not self.recover():
                break
        return ok

    def run_forever(self) -> None:
        """Vòng lặp chính: N lượt march → chờ → lặp lại."""
        while not self.should_stop():
            ok = self.run_round()
            if self.should_stop():
                break
            log.info(
                "Cycle done: %d/%d marches. Waiting %g minutes.",
                ok, self.cfg.marches_per_round, self.cfg.wait_minutes,
            )
            if not self.sleep(self.cfg.wait_seconds):
                break
