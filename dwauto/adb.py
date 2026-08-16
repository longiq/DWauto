"""Chụp màn hình qua ADB thay vì chụp màn hình máy.

Vì sao tốt hơn cho việc "để cửa sổ ở đâu cũng chạy":
  - ảnh lấy thẳng từ Android nên luôn cùng độ phân giải (1080x1920), không phụ
    thuộc cửa sổ to nhỏ hay nằm đâu — template không bao giờ lệch tỉ lệ;
  - cửa sổ bị che một phần vẫn NHÌN được (chỉ lúc click mới cần nó hiện ra);
  - không cần quyền Screen Recording trên macOS.

Giới hạn đã đo trên BlueStacks Air 5.21.770 (macOS): adbd của nó là bản shim, chỉ
chạy `getprop`, `dumpsys`, `screencap`. `input tap` bị chặn (`error: closed`) nên
phần CLICK vẫn phải đi qua chuột thật — tức cửa sổ vẫn phải hiện và không bị che.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from dwauto.screen import DEFAULT_THRESHOLD, Match, find_template
from dwauto.window import WindowRect, find_window, game_rect, title_bar_height

log = logging.getLogger(__name__)

DEFAULT_PORT = 5555
# Cổng ADB hay gặp: BlueStacks, BlueStacks instance phụ, LDPlayer, Nox, MEmu.
COMMON_PORTS = (5555, 5565, 5575, 5554, 62001, 21503)


class AdbUnavailable(Exception):
    """Không kết nối được ADB, hoặc emulator không cho chụp màn hình."""


def connect(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 5.0):
    from adb_shell.adb_device import AdbDeviceTcp

    dev = AdbDeviceTcp(host, port, default_transport_timeout_s=30)
    try:
        dev.connect(auth_timeout_s=timeout)
    except Exception as exc:
        raise AdbUnavailable(f"Cannot connect to ADB at {host}:{port} ({exc})") from exc
    return dev


def scan_ports(host: str = "127.0.0.1", ports=COMMON_PORTS) -> int | None:
    """Dò cổng ADB nào đang sống — mỗi instance giả lập một cổng khác nhau."""
    import socket

    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return port
        except OSError:
            continue
    return None


class AdbScreen:
    """Cùng giao diện với Screen (capture/find/wait_for/to_mouse) nhưng chụp qua ADB.

    Toạ độ trả về nằm trong "không gian template": ảnh Android được co về đúng bề
    ngang lúc cắt template (`template_width`), nên template cũ dùng lại được và
    không phụ thuộc kích thước cửa sổ hiện tại.
    """

    def __init__(
        self,
        template_width: int = 506,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        window_title: str = "BlueStacks",
        device=None,
        adb_binary: str | None = None,
    ):
        self.template_width = template_width
        self.host = host
        self.port = port
        self.window_title = window_title
        self._dev = device
        self.adb_binary = adb_binary
        self.raw_size: tuple[int, int] | None = None  # (w, h) của màn Android
        self._warned_titlebar = False

    # ---------- kết nối ----------

    @property
    def device(self):
        if self._dev is None:
            self._dev = connect(self.host, self.port)
        return self._dev

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def __enter__(self) -> AdbScreen:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------- chụp ----------

    def grab_raw(self) -> np.ndarray:
        """Ảnh gốc từ Android (BGR), đúng độ phân giải thật của emulator."""
        if self.adb_binary:
            png = self._grab_raw_via_binary()
        else:
            try:
                png = self.device.exec_out(
                    "screencap -p", decode=False, read_timeout_s=25, transport_timeout_s=25
                )
            except Exception as exc:
                self.close()
                raise AdbUnavailable(f"screencap failed: {exc}") from exc
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbUnavailable(f"screencap returned non-image data ({len(png)} bytes)")
        self.raw_size = (img.shape[1], img.shape[0])
        return img

    def _grab_raw_via_binary(self) -> bytes:
        """Chụp qua adb binary thật (subprocess) thay vì thư viện adb_shell.

        Một số adbd của emulator (đo trên MuMu Player) không tương thích với
        exec_out của thư viện adb_shell thuần Python — treo tới hết timeout dù
        adb binary thật trả kết quả trong dưới 1 giây. Dùng khi 'capture.adb_binary'
        được khai trong config.
        """
        import subprocess

        try:
            proc = subprocess.run(
                [self.adb_binary, "-s", f"{self.host}:{self.port}", "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=25,
                check=True,
            )
        except Exception as exc:
            raise AdbUnavailable(f"screencap (adb binary) failed: {exc}") from exc
        return proc.stdout

    def capture(self) -> np.ndarray:
        """Ảnh đã co về đúng tỉ lệ lúc cắt template."""
        raw = self.grab_raw()
        h = round(self.template_width * raw.shape[0] / raw.shape[1])
        return cv2.resize(raw, (self.template_width, h), interpolation=cv2.INTER_AREA)

    # ---------- tìm ----------

    def find(
        self,
        template: str | Path | np.ndarray,
        threshold: float = DEFAULT_THRESHOLD,
        region=None,
        screen: np.ndarray | None = None,
    ) -> Match | None:
        img = self.capture() if screen is None else screen
        return find_template(img, template, threshold, region)

    def wait_for(
        self,
        template: str | Path | np.ndarray,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: float = DEFAULT_THRESHOLD,
        region=None,
    ) -> Match | None:
        deadline = time.monotonic() + timeout
        while True:
            m = self.find(template, threshold, region)
            if m is not None:
                return m
            if time.monotonic() >= deadline:
                return None
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    # ---------- quy đổi toạ độ ----------

    def window(self) -> WindowRect:
        """Dò lại vị trí cửa sổ mỗi lần gọi → kéo cửa sổ giữa chừng vẫn đúng."""
        return find_window(self.window_title)

    def to_mouse(self, x: float, y: float) -> tuple[int, int]:
        """Toạ độ trong ảnh template → toạ độ chuột trên màn hình.

        Đi qua vùng game thật bên trong cửa sổ, nên cửa sổ ở đâu / to nhỏ ra sao
        cũng ra đúng điểm.
        """
        if self.raw_size is None:
            self.grab_raw()
        raw_w, raw_h = self.raw_size
        win = self.window()
        gx, gy, gw, gh = game_rect(win, raw_w, raw_h)

        bar = title_bar_height(win, raw_w, raw_h)
        if not self._warned_titlebar and not (-2 <= bar <= 120):
            self._warned_titlebar = True
            log.warning(
                "Title bar computed as %.0fpx, which is unusual. Window %dx%d may not match "
                "the Android screen ratio %dx%d (landscape? extra chrome?). Clicks may be off.",
                bar, win.width, win.height, raw_w, raw_h,
            )

        th = self.template_width * raw_h / raw_w  # chiều cao ảnh template
        return round(gx + x * gw / self.template_width), round(gy + y * gh / th)

    def to_device(self, x: float, y: float) -> tuple[int, int]:
        """Toạ độ trong ảnh template → toạ độ Android thật, cho AdbMouse.

        Không cần dò cửa sổ: ảnh ADB luôn đúng độ phân giải thật của emulator,
        nên chỉ cần nhân theo tỉ lệ template_width / raw_w.
        """
        if self.raw_size is None:
            self.grab_raw()
        raw_w, raw_h = self.raw_size
        factor = raw_w / self.template_width
        return round(x * factor), round(y * factor)
