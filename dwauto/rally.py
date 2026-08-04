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
    expect: str  # template phải hiện ra sau khi click thành công


STEPS = (
    Step("search", "search_button", "search_confirm"),
    Step("confirm", "search_confirm", "rally_button"),
    Step("rally", "rally_button", "march_button"),
    Step("march", "march_button", "search_button"),
)

# Hỏng liên tiếp bấy nhiêu lượt thì bỏ vòng, chờ tới vòng sau. Không có chặn này thì
# game kẹt ở world map (hết lượt march, hết quân...) sẽ bị click liên tục vô ích.
MAX_CONSECUTIVE_FAILURES = 2


class RallyRunner:
    def __init__(self, screen, mouse, cfg, should_stop: Callable[[], bool] | None = None):
        self.screen = screen
        self.mouse = mouse
        self.cfg = cfg
        self.should_stop = should_stop or (lambda: False)
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
            threshold=self.cfg.threshold,
        )

    def _find(self, name: str):
        return self.screen.find(self._tpl(name), threshold=self.cfg.threshold)

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
            log.warning("[%s] không thấy %s → bỏ lượt này", step.name, step.template)
            return False

        for attempt in range(self.cfg.retries + 1):
            mx, my = self.screen.to_mouse(match.x, match.y)
            self.mouse.click(mx, my, label=f"{step.name}/{step.template}")

            if self._wait(step.expect) is not None:
                return True

            if attempt < self.cfg.retries:
                log.warning(
                    "[%s] click xong không thấy %s (lần %d/%d) → thử lại",
                    step.name, step.expect, attempt + 1, self.cfg.retries,
                )
                if self.should_stop():
                    return False
                again = self._find(step.template)
                if again is None:
                    # Nút biến mất mà màn hình kế cũng chưa hiện → đang chuyển cảnh.
                    log.warning("[%s] %s cũng biến mất, chờ thêm", step.name, step.template)
                    if self._wait(step.expect) is not None:
                        return True
                    return False
                match = again

        log.error("[%s] thất bại sau %d lần click", step.name, self.cfg.retries + 1)
        return False

    # ---------- một lượt march ----------

    def march_once(self) -> bool:
        for step in STEPS:
            if self.should_stop():
                return False
            if not self.do_step(step):
                self.marches_failed += 1
                return False
        self.marches_done += 1
        log.info("March xong (tổng %d thành công / %d hỏng)", self.marches_done, self.marches_failed)
        return True

    def recover(self) -> bool:
        """Sau một lượt hỏng: chờ quay lại được world map thì mới đi tiếp."""
        log.info("Đang tìm đường về world map...")
        if self._wait("search_button", timeout=self.cfg.step_timeout * 2) is not None:
            return True
        log.error("Không về được world map — kiểm tra lại game/cửa sổ giả lập")
        return False

    # ---------- một vòng ----------

    def run_round(self) -> int:
        """Chạy `marches_per_round` lượt liên tiếp. Trả số lượt thành công."""
        ok = 0
        consecutive_fail = 0
        for i in range(self.cfg.marches_per_round):
            if self.should_stop():
                break
            log.info("--- Lượt %d/%d ---", i + 1, self.cfg.marches_per_round)
            if self.march_once():
                ok += 1
                consecutive_fail = 0
                continue

            consecutive_fail += 1
            if consecutive_fail >= MAX_CONSECUTIVE_FAILURES:
                log.error("Hỏng %d lượt liên tiếp → bỏ vòng này, chờ vòng sau", consecutive_fail)
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
                "Vòng xong: %d/%d lượt. Chờ %g phút.",
                ok, self.cfg.marches_per_round, self.cfg.wait_minutes,
            )
            if not self.sleep(self.cfg.wait_seconds):
                break
