"""Test state machine rally bằng game giả — không cần màn hình, không click thật."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from dwauto.actions import Mouse
from dwauto.config import Config
from dwauto.rally import STEPS, RallyRunner
from dwauto.screen import Match

# Toạ độ nút lấy từ bản ghi thật (recordings_mac), theo pixel ảnh chụp.
BUTTONS = {
    "search_button": (31, 767),
    "rally_tab_button": (400, 400),
    "search_confirm": (458, 868),
    "rally_button": (258, 561),
    "march_button": (294, 708),
}
# Màn hình nào hiện nút nào + click vào đó thì chuyển sang màn hình nào.
# "panel_pretab" mô phỏng panel Search vừa mở, chưa chắc đúng tab Rally — game
# thật hiện rally_tab_button và search_confirm CÙNG LÚC (update 21/08/2026),
# đơn giản hoá thành 2 state nối tiếp vẫn đủ để test đúng thứ tự + số bước.
VISIBLE = {
    "world_map": "search_button",
    "panel_pretab": "rally_tab_button",
    "panel": "search_confirm",
    "target": "rally_button",
    "march": "march_button",
}
NEXT = {
    "world_map": "panel_pretab",
    "panel_pretab": "panel",
    "panel": "target",
    "target": "march",
    "march": "world_map",
}


class FakeGame:
    """Giả lập game: mỗi màn hình hiện đúng một nút, click trúng thì chuyển màn."""

    def __init__(self, eat_clicks: int = 0, dead_button: str | None = None):
        self.state = "world_map"
        self.eat_clicks = eat_clicks  # số click đầu bị macOS nuốt (focus cửa sổ)
        self.dead_button = dead_button  # nút bấm mãi không ăn
        self.clicks: list[tuple[int, int]] = []
        self.captures = 0

    # --- phía Screen ---
    def find(self, template, threshold=0.85, region=None, screen=None):
        self.captures += 1
        name = Path(str(template)).stem
        if VISIBLE[self.state] != name:
            return None
        x, y = BUTTONS[name]
        return Match(x=x, y=y, score=0.99, left=x - 10, top=y - 10, width=20, height=20)

    def wait_for(self, template, timeout=5.0, interval=0.05, threshold=0.85, region=None):
        deadline = time.monotonic() + timeout
        while True:
            m = self.find(template, threshold)
            if m is not None or time.monotonic() >= deadline:
                return m
            time.sleep(min(interval, 0.01))

    def to_mouse(self, x, y):
        return x + 149, y + 84  # capture_area offset, scale 1.0

    # --- phía Mouse ---
    def click(self, mx, my, label=""):
        self.clicks.append((mx, my))
        if self.eat_clicks > 0:
            self.eat_clicks -= 1
            return mx, my
        name = VISIBLE[self.state]
        bx, by = self.to_mouse(*BUTTONS[name])
        if abs(mx - bx) <= 12 and abs(my - by) <= 12 and name != self.dead_button:
            self.state = NEXT[self.state]
        return mx, my


def make_cfg(**over) -> Config:
    base = dict(
        region={"left": 149, "top": 84, "width": 506, "height": 932},
        threshold=0.85,
        templates={n: Path(f"templates/{n}.png") for n in BUTTONS},
        marches_per_round=3,
        wait_minutes=0.0,
        step_timeout=0.3,
        poll_interval=0.01,
        retries=2,
        click_delay=(0.0, 0.0),
        offset_px=0,
        move_duration=(0.0, 0.0),
    )
    base.update(over)
    return Config(**base)


def runner(game: FakeGame, cfg: Config | None = None, should_stop=None) -> RallyRunner:
    return RallyRunner(game, game, cfg or make_cfg(), should_stop=should_stop)


# ---------- luồng bình thường ----------


def test_mot_luot_march_du_5_click():
    game = FakeGame()
    r = runner(game)
    assert r.march_once() is True
    assert len(game.clicks) == 5
    assert game.state == "world_map"  # quay lại map, sẵn sàng lượt kế
    assert (r.marches_done, r.marches_failed) == (1, 0)


def test_click_dung_toa_do_chuot_khong_phai_pixel_anh():
    """Nút search ở pixel ảnh (31,767) → phải click ở (180,851) trên màn hình."""
    game = FakeGame()
    runner(game).march_once()
    assert game.clicks[0] == (31 + 149, 767 + 84)


def test_thu_tu_buoc_dung_spec():
    assert [s.template for s in STEPS] == [
        "search_button", "rally_tab_button", "search_confirm", "rally_button", "march_button",
    ]
    # Bước cuối expect=None: xác nhận bằng việc nút March biến mất, vì world map
    # chưa hiện ngay sau khi bấm (game chạy animation bay tới điểm tập kết).
    assert [s.expect for s in STEPS] == [
        "rally_tab_button", "search_confirm", "rally_button", "march_button", None,
    ]


def test_ba_luot_moi_vong():
    game = FakeGame()
    r = runner(game)
    assert r.run_round() == 3
    assert len(game.clicks) == 15
    assert r.marches_done == 3


# ---------- click bị nuốt / hỏng ----------


def test_click_dau_bi_nuot_van_march_duoc():
    """Lỗi thật đã gặp: BlueStacks chưa focus, click đầu chỉ để focus cửa sổ."""
    game = FakeGame(eat_clicks=1)
    r = runner(game)
    assert r.march_once() is True
    assert len(game.clicks) == 6  # 5 click thật + 1 click bị nuốt phải bấm lại
    assert game.clicks[0] == game.clicks[1]  # click lại đúng chỗ cũ


def test_nut_khong_an_thi_bo_luot_sau_khi_thu_du_so_lan():
    game = FakeGame(dead_button="rally_button")
    cfg = make_cfg(retries=2)
    r = runner(game, cfg)
    assert r.march_once() is False
    assert r.marches_failed == 1
    # search + rally_tab + confirm = 3 click, rồi rally bấm 1 + 2 lần thử lại = 3
    assert len(game.clicks) == 6


def test_khong_thay_nut_thi_khong_click_bua():
    game = FakeGame()
    game.state = "target"  # đang kẹt ở popup, không có search_button
    r = runner(game)
    assert r.march_once() is False
    assert game.clicks == []


def test_recover_cho_ve_world_map():
    game = FakeGame()
    game.state = "march"
    r = runner(game)
    assert r.recover() is False  # đang ở panel March, không thấy world map
    game.state = "world_map"
    assert r.recover() is True


def test_bo_vong_khi_hong_lien_tiep():
    """Game kẹt (nút không ăn) → không được spam click hết cả vòng."""
    game = FakeGame(dead_button="search_button")
    r = runner(game, make_cfg(marches_per_round=3, retries=2))
    assert r.run_round() == 0
    assert r.marches_failed == 2  # bỏ vòng sau 2 lượt hỏng liên tiếp, không thử lượt 3
    assert len(game.clicks) == 6  # 2 lượt x 3 lần click, chứ không phải 9


def test_hong_mot_luot_roi_ok_thi_van_chay_tiep():
    game = FakeGame(eat_clicks=1)
    r = runner(game, make_cfg(marches_per_round=3, retries=0))
    assert r.run_round() == 2  # lượt 1 hỏng vì click bị nuốt (không có retry), 2 lượt sau ok
    assert (r.marches_done, r.marches_failed) == (2, 1)


# ---------- dừng giữa chừng ----------


def test_should_stop_chan_luot_ke():
    game = FakeGame()
    stop = {"v": False}
    r = runner(game, should_stop=lambda: stop["v"])
    assert r.march_once() is True
    stop["v"] = True
    assert r.march_once() is False
    assert len(game.clicks) == 5  # không click thêm sau khi bị yêu cầu dừng


def test_sleep_ngat_duoc_khong_cho_het_gio():
    game = FakeGame()
    stop = {"v": True}
    r = runner(game, should_stop=lambda: stop["v"])
    t0 = time.monotonic()
    assert r.sleep(30.0) is False
    assert time.monotonic() - t0 < 1.0


def test_sleep_binh_thuong_thi_cho_du():
    r = runner(FakeGame())
    t0 = time.monotonic()
    assert r.sleep(0.2) is True
    assert time.monotonic() - t0 >= 0.19


def test_run_forever_dung_khi_bi_yeu_cau_dung():
    game = FakeGame()
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > 40  # dừng sau một số lần kiểm tra

    r = runner(game, make_cfg(wait_minutes=0.0), should_stop=stop)
    r.run_forever()  # phải kết thúc, không treo


# ---------- Mouse ----------


def test_dry_run_khong_dung_toi_pyautogui(caplog):
    m = Mouse(offset_px=0, dry_run=True)
    with caplog.at_level("INFO"):
        assert m.click(500, 400, label="march") == (500, 400)
    assert m._pyautogui is None  # không import, không chạm chuột thật
    assert "would click at (500, 400)" in caplog.text


@pytest.mark.parametrize("offset", [0, 1, 5])
def test_jitter_nam_trong_bien(offset):
    m = Mouse(offset_px=offset, rng=random.Random(0))
    for _ in range(50):
        x, y = m.jitter(300, 200)
        assert abs(x - 300) <= offset and abs(y - 200) <= offset


def test_jitter_that_su_ngau_nhien():
    m = Mouse(offset_px=4, rng=random.Random(1))
    assert len({m.jitter(300, 200) for _ in range(40)}) > 1


# ---------- bước cuối xác nhận bằng "nút biến mất" ----------


class SlowMapGame(FakeGame):
    """Sau March, world map hiện chậm (animation bay tới điểm tập kết)."""

    def __init__(self, delay_polls: int = 5):
        super().__init__()
        self.delay_polls = delay_polls
        self.in_transition = 0

    def click(self, mx, my, label=""):
        was = self.state
        r = super().click(mx, my, label)
        if was == "march" and self.state == "world_map":
            self.in_transition = self.delay_polls  # chưa nút nào hiện
        return r

    def find(self, template, threshold=0.85, region=None, screen=None):
        if self.in_transition > 0:
            self.captures += 1
            self.in_transition -= 1
            return None  # màn chuyển cảnh: không thấy nút nào cả
        return super().find(template, threshold, region, screen)


def test_march_tinh_la_xong_khi_panel_dong_du_map_chua_hien():
    """Lỗi thật đã gặp: bắt phải thấy world map ngay sau March → báo hỏng oan."""
    game = SlowMapGame(delay_polls=5)
    r = runner(game, make_cfg(step_timeout=0.3, poll_interval=0.01))
    assert r.march_once() is True
    assert (r.marches_done, r.marches_failed) == (1, 0)
    assert len(game.clicks) == 5  # không click lại thừa


def test_march_van_hong_neu_panel_khong_dong():
    """Panel March không đóng (hết quân, lỗi trong game) → phải báo hỏng."""
    game = FakeGame(dead_button="march_button")
    r = runner(game, make_cfg(retries=1))
    assert r.march_once() is False
    assert game.state == "march"
