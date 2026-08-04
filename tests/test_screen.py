"""Test logic matching bằng ảnh tổng hợp — không cần màn hình, không cần mss.grab."""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from dwauto import screen as S

SCREEN_W, SCREEN_H = 800, 600
BTN_W, BTN_H = 60, 30
BTN_X, BTN_Y = 300, 200  # góc trên-trái của "nút" trong ảnh nền


def make_screen(seed: int = 0) -> np.ndarray:
    """Ảnh nền nhiễu (không phẳng — TM_CCOEFF_NORMED cần có phương sai)."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (SCREEN_H, SCREEN_W, 3), dtype=np.uint8)


def paste(bg: np.ndarray, patch: np.ndarray, x: int, y: int) -> np.ndarray:
    out = bg.copy()
    h, w = patch.shape[:2]
    out[y : y + h, x : x + w] = patch
    return out


@pytest.fixture
def button() -> np.ndarray:
    rng = np.random.default_rng(99)
    return rng.integers(0, 256, (BTN_H, BTN_W, 3), dtype=np.uint8)


@pytest.fixture
def screen_with_button(button: np.ndarray) -> np.ndarray:
    return paste(make_screen(), button, BTN_X, BTN_Y)


# ---------- find_template ----------


def test_tim_thay_dung_tam(screen_with_button, button):
    m = S.find_template(screen_with_button, button)
    assert m is not None
    assert (m.x, m.y) == (BTN_X + BTN_W // 2, BTN_Y + BTN_H // 2)
    assert (m.left, m.top, m.width, m.height) == (BTN_X, BTN_Y, BTN_W, BTN_H)
    assert m.score == pytest.approx(1.0, abs=1e-6)


def test_khong_co_thi_tra_none(button):
    assert S.find_template(make_screen(seed=1), button) is None


def test_nguong_quyet_dinh(screen_with_button, button):
    """Nút bị nhiễu nhẹ: qua ở ngưỡng thấp, trượt ở ngưỡng cao."""
    rng = np.random.default_rng(7)
    noisy = np.clip(
        button.astype(np.int16) + rng.integers(-70, 71, button.shape), 0, 255
    ).astype(np.uint8)
    score = S.find_template(screen_with_button, noisy, threshold=0.0).score
    assert 0.0 < score < 1.0
    assert S.find_template(screen_with_button, noisy, threshold=score - 0.01) is not None
    assert S.find_template(screen_with_button, noisy, threshold=score + 0.01) is None


def test_nguong_mac_dinh_la_085():
    assert S.DEFAULT_THRESHOLD == 0.85


# ---------- region ----------


def test_region_cong_lai_offset(screen_with_button, button):
    """Toạ độ trả về phải là toạ độ ảnh gốc, không phải toạ độ trong region."""
    m = S.find_template(screen_with_button, button, region=(250, 150, 500, 400))
    assert m is not None
    assert (m.x, m.y) == (BTN_X + BTN_W // 2, BTN_Y + BTN_H // 2)


def test_region_khong_chua_nut(screen_with_button, button):
    assert S.find_template(screen_with_button, button, region=(0, 0, 200, 150)) is None


def test_region_bi_cat_theo_bien_anh(screen_with_button, button):
    """Region tràn ra ngoài ảnh vẫn tìm được, không ném lỗi."""
    m = S.find_template(screen_with_button, button, region=(-100, -100, 9999, 9999))
    assert m is not None and (m.left, m.top) == (BTN_X, BTN_Y)


@pytest.mark.parametrize("region", [(300, 200, 300, 400), (300, 200, 500, 200), (500, 0, 100, 100)])
def test_region_rong_tra_none(screen_with_button, button, region):
    assert S.find_template(screen_with_button, button, region=region) is None


def test_region_nho_hon_template(screen_with_button, button):
    """Region bé hơn template → None chứ không để cv2 ném lỗi."""
    assert S.find_template(screen_with_button, button, region=(300, 200, 320, 210)) is None


# ---------- biên & định dạng ảnh ----------


def test_template_lon_hon_man_hinh(button):
    big = np.zeros((SCREEN_H + 10, SCREEN_W + 10, 3), dtype=np.uint8)
    assert S.find_template(button, big) is None


def test_anh_xam_va_bgra(screen_with_button, button):
    gray = cv2.cvtColor(screen_with_button, cv2.COLOR_BGR2GRAY)
    assert S.find_template(gray, cv2.cvtColor(button, cv2.COLOR_BGR2GRAY)) is not None
    bgra = cv2.cvtColor(screen_with_button, cv2.COLOR_BGR2BGRA)
    m = S.find_template(bgra, cv2.cvtColor(button, cv2.COLOR_BGR2BGRA))
    assert m is not None and (m.left, m.top) == (BTN_X, BTN_Y)


def test_nut_sat_goc_phai_duoi(button):
    x, y = SCREEN_W - BTN_W, SCREEN_H - BTN_H
    m = S.find_template(paste(make_screen(), button, x, y), button)
    assert m is not None and (m.left, m.top) == (x, y)


# ---------- load_template ----------


def test_load_template_doc_va_cache(tmp_path, button, screen_with_button):
    p = tmp_path / "search_button.png"
    cv2.imwrite(str(p), button)
    assert np.array_equal(S.load_template(p), S.load_template(str(p)))
    m = S.find_template(screen_with_button, p)
    assert m is not None and (m.left, m.top) == (BTN_X, BTN_Y)


def test_cache_thay_moi_khi_file_doi(tmp_path, button):
    p = tmp_path / "t.png"
    cv2.imwrite(str(p), button)
    first = S.load_template(p).copy()
    other = np.random.default_rng(5).integers(0, 256, (BTN_H, BTN_W, 3), dtype=np.uint8)
    time.sleep(0.01)
    cv2.imwrite(str(p), other)
    assert not np.array_equal(S.load_template(p), first)


def test_template_khong_ton_tai(tmp_path):
    with pytest.raises(FileNotFoundError):
        S.load_template(tmp_path / "khong_co.png")


def test_file_hong(tmp_path):
    p = tmp_path / "hong.png"
    p.write_bytes(b"khong phai anh")
    with pytest.raises(ValueError):
        S.load_template(p)


# ---------- quy đổi toạ độ (Retina / DPI scaling) ----------


def test_image_to_mouse_scale_1():
    area = {"left": 0, "top": 0, "width": SCREEN_W, "height": SCREEN_H}
    assert S.image_to_mouse(330, 215, area, (1.0, 1.0)) == (330, 215)


def test_image_to_mouse_retina():
    """Retina: pixel ảnh gấp đôi toạ độ chuột."""
    area = {"left": 0, "top": 0, "width": SCREEN_W, "height": SCREEN_H}
    assert S.image_to_mouse(800, 600, area, (2.0, 2.0)) == (400, 300)


def test_image_to_mouse_co_offset_vung_chup():
    """Chụp theo --region: phải cộng lại gốc của vùng."""
    area = {"left": 100, "top": 80, "width": 900, "height": 600}
    assert S.image_to_mouse(600, 440, area, (2.0, 2.0)) == (400, 300)


def test_screen_to_mouse_dung_scale_da_do():
    sc = S.Screen(area={"left": 100, "top": 80, "width": 900, "height": 600}, scale=(2.0, 2.0))
    assert sc.to_mouse(600, 440) == (400, 300)


# ---------- Screen.find / wait_for (không đụng mss) ----------


class FakeScreen(S.Screen):
    """Screen trả về ảnh dựng sẵn thay vì chụp màn hình thật."""

    def __init__(self, frames: list[np.ndarray], **kw):
        super().__init__(area={"left": 0, "top": 0, "width": SCREEN_W, "height": SCREEN_H}, **kw)
        self.frames = frames
        self.n_capture = 0

    def capture(self) -> np.ndarray:
        self.n_capture += 1
        return self.frames[min(self.n_capture - 1, len(self.frames) - 1)]


def test_find_dung_anh_cho_san_thi_khong_chup(screen_with_button, button):
    sc = FakeScreen([make_screen(seed=1)])
    m = sc.find(button, screen=screen_with_button)
    assert m is not None and sc.n_capture == 0


def test_wait_for_thay_o_lan_poll_sau(screen_with_button, button):
    sc = FakeScreen([make_screen(seed=1), make_screen(seed=2), screen_with_button])
    m = sc.wait_for(button, timeout=2.0, interval=0.01)
    assert m is not None and (m.x, m.y) == (BTN_X + BTN_W // 2, BTN_Y + BTN_H // 2)
    assert sc.n_capture == 3


def test_wait_for_het_gio_tra_none(button):
    sc = FakeScreen([make_screen(seed=1)])
    t0 = time.monotonic()
    assert sc.wait_for(button, timeout=0.2, interval=0.05) is None
    assert 0.15 <= time.monotonic() - t0 < 2.0
    assert sc.n_capture >= 2


def test_wait_for_timeout_0_van_thu_mot_lan(screen_with_button, button):
    sc = FakeScreen([screen_with_button])
    assert sc.wait_for(button, timeout=0.0) is not None
    assert sc.n_capture == 1
