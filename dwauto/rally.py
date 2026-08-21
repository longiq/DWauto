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
    # Cập nhật 21/08/2026 (game update, đổi layout panel Search): giờ có 3 tab
    # Jungle | Gather | Rally, cả rally_tab_button lẫn search_confirm hiện đồng
    # thời ngay khi panel mở (bất kể tab nào đang chọn) — dùng rally_tab_button
    # làm dấu hiệu "đã mở đúng panel" cho bước search, RỒI mới bấm nó (đúng tab
    # hay chưa cũng không sao, bấm lại tab đang chọn không đổi gì) để chắc chắn
    # tìm đúng loại mục tiêu trước khi tin search_confirm sẽ search đúng Rally.
    Step("search", "search_button", "rally_tab_button"),
    Step("rally_tab", "rally_tab_button", "search_confirm"),
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

    def _has_template(self, name: str) -> bool:
        return name in self.cfg.templates

    def _click_match(self, match, label: str) -> None:
        if getattr(self.mouse, "uses_device_coords", False):
            mx, my = self.screen.to_device(match.x, match.y)
        else:
            mx, my = self.screen.to_mouse(match.x, match.y)
        self.mouse.click(mx, my, label=label)

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
        if self._wait(step.expect) is not None:
            return True
        # Bước "rally" chờ march_button hiện ra sau khi bấm Rally — nhưng rally
        # đã đầy quân (troop tổng của rally vượt giới hạn) thì March hiện ra bị
        # khoá (xám) thay vì bấm được, cùng vị trí/kích thước nhưng khác template.
        # Vẫn coi là "đã tới nơi" để bước march sau xử lý bỏ qua có kiểm soát
        # (_skip_if_march_locked) — không có nhánh này thì do_step("rally") coi
        # là thất bại luôn, không bao giờ chạy tới bước "march" để nhận biết.
        if step.expect == "march_button" and self._has_template("march_button_disabled"):
            return self._find("march_button_disabled") is not None
        return False

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
            self._click_match(match, label=f"{step.name}/{step.template}")

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

    # ---------- hết energy ----------

    def _refill_energy_if_needed(self) -> None:
        """Hết energy thì nút March đổi thành Get Energy — cùng vị trí/kích thước,
        chỉ khác chữ. Tự bấm Get Energy → x20 (dùng luôn item "10 Energy" có sẵn
        trong túi, game tự áp dụng + đóng popup, không cần bấm Use riêng) → chờ
        quay lại panel March, rồi để do_step(march) làm tiếp như bình thường.

        Không cấu hình 2 template này, còn đủ energy (còn thấy march_button), hoặc
        không tìm thấy Get Energy (hết vì lý do khác) thì bỏ qua im lặng — do_step
        tự báo lỗi theo đường cũ. Hết sạch item "10 Energy" (không thấy nút x20)
        cũng bỏ qua — không có gì bù thêm được, march sẽ báo lỗi bình thường.
        """
        if not self._has_template("get_energy_button") or not self._has_template("energy_x20_button"):
            return
        if self._find("march_button") is not None:
            return
        energy_btn = self._find("get_energy_button")
        if energy_btn is None:
            return

        log.info("[energy] Hết energy - bấm Get Energy")
        self._click_match(energy_btn, label="energy/get_energy_button")

        x20 = self._wait("energy_x20_button")
        if x20 is None:
            log.warning("[energy] Không thấy nút x20 (có thể hết item nạp energy) - bỏ qua")
            return
        log.info("[energy] Bấm x20 để dùng item nạp energy")
        self._click_match(x20, label="energy/energy_x20_button")
        self._wait("march_button")  # chờ quay lại panel March trước khi march tiếp

    # ---------- rally đã đầy quân ----------

    # Toạ độ Android thật, ngoài khung panel March/target (khung chiếm khoảng
    # x:227-903, y:435-1270) — rơi vào vùng biển trống bên phải world map.
    # Verify bằng tay 20/08/2026: tap đây đóng popup, không mở thêm gì khác.
    _DISMISS_TAP = (800, 950)

    def _dismiss_popup(self) -> bool:
        """Tap ra ngoài popup để đóng nó — panel March không có nút X, và
        KEYCODE_BACK Android **KHÔNG AN TOÀN**: verify bằng tay 20/08/2026, Back
        bị game hiểu là thoát app, bật hộp thoại "Quit the game?" — nếu vô tình
        chạy tiếp mà không xử lý, có nguy cơ auto-thoát cả game. Tuyệt đối không
        dùng adb input keyevent KEYCODE_BACK ở đây hay bất cứ đâu trong rally.py.

        Chỉ làm được khi dùng AdbMouse (có sẵn adb_binary + target ADB thật) —
        backend Mouse (chuột thật) không dùng tính năng này, bỏ qua."""
        if not getattr(self.mouse, "uses_device_coords", False):
            return False
        x, y = self._DISMISS_TAP
        self.mouse.click(x, y, label="march/dismiss_popup")
        return True

    def _skip_if_march_locked(self) -> bool:
        """Rally đã đầy quân (tổng troop CỦA RALLY vượt giới hạn — không phải của
        mình) thì March bị khoá: hiện đúng vị trí/kích thước march_button nhưng
        màu xám, không có cách nào march được (không giống hết energy, không có
        gì bù). Trước đây tool cứ chờ đủ step_timeout rồi mới báo lỗi, verify thật
        20/08/2026: kẹt hẳn ở panel này rất lâu vì recover() sau đó cũng không
        thấy world map (còn đang ở panel March, chưa thoát) — đúng bug người dùng
        báo "kẹt tại nút rally, tưởng là click nhầm chỗ".

        Tap ra ngoài popup để đóng ngay thay vì chờ vô ích, coi lượt này là bỏ qua
        có kiểm soát. Không cấu hình template này thì bỏ qua, để hành vi cũ (chờ
        rồi báo lỗi qua do_step) vẫn chạy như trước.
        """
        if not self._has_template("march_button_disabled"):
            return False
        if self._find("march_button") is not None:
            return False
        if self._find("march_button_disabled") is None:
            return False
        log.info("[march] Rally đã đầy quân (troop vượt giới hạn) - bỏ qua, thoát về world map")
        if self._dismiss_popup():
            self._wait("search_button", timeout=self.cfg.step_timeout)
        return True

    # ---------- một lượt march ----------

    def march_once(self) -> bool:
        if not self.focus():
            log.debug("Could not raise the emulator window - the first click may be swallowed")
        for step in STEPS:
            if self.should_stop():
                return False
            if step.name == "march":
                self._refill_energy_if_needed()
                if self._skip_if_march_locked():
                    self.marches_failed += 1
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
