"""Chế độ GHI: log click + screenshot + tự cắt template ứng viên.

Chạy được trên cả hai môi trường mục tiêu:
  - macOS + BlueStacks (Retina → ảnh chụp là pixel vật lý, gấp 2 lần toạ độ chuột).
  - Windows + app/giả lập của game (DPI scaling >100% cũng lệch tương tự).
Tỉ lệ scale được đo lúc chạy (kích thước ảnh chụp / kích thước vùng chụp) nên cùng
một đoạn code xử lý được cả hai; scale được ghi vào clicks.json cho giai đoạn sau.

Cách dùng:
    python recorder.py                          # ghi vào recordings/
    python recorder.py --region 100,80,900,1600 # chỉ chụp cửa sổ giả lập
    python recorder.py --start-key f7           # đổi phím tắt (macOS hay vướng F8)

Phím tắt (mặc định):
    F8  bật/tắt ghi
    F9  chụp 1 frame không kèm click (dùng cho popup "target under attack")
    Esc thoát
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import mss
import numpy as np
from pynput import keyboard, mouse

DEFAULT_CROP = (120, 60)
IS_MAC = platform.system() == "Darwin"

# mss >= 10 đổi tên mss.mss() thành mss.MSS(); giữ tương thích cả hai.
_MSS = getattr(mss, "MSS", None) or mss.mss

# mss không an toàn khi dùng chung giữa nhiều thread (mouse listener và keyboard
# listener chạy trên 2 thread khác nhau) → mỗi thread giữ một instance riêng.
_local = threading.local()


def _sct():
    sct = getattr(_local, "sct", None)
    if sct is None:
        sct = _MSS()
        _local.sct = sct
    return sct


def key_name(key) -> str | None:
    """Chuẩn hoá key của pynput về chuỗi để so sánh ('f8', 'esc', 'a', ...)."""
    name = getattr(key, "name", None)
    if name:
        return name.lower()
    char = getattr(key, "char", None)
    return char.lower() if char else None


class Recorder:
    def __init__(
        self,
        out_dir: Path,
        crop_size: tuple[int, int],
        monitor_index: int,
        region: tuple[int, int, int, int] | None = None,
        keys: dict[str, str] | None = None,
    ):
        self.out_dir = out_dir
        self.frames_dir = out_dir / "frames"
        self.crops_dir = out_dir / "crops"
        self.crop_w, self.crop_h = crop_size
        self.monitor_index = monitor_index
        self.keys = keys or {"start": "f8", "snap": "f9", "quit": "esc"}

        self.events: list[dict] = []
        self.recording = False
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.scale = (1.0, 1.0)  # đo lại ở lần chụp đầu tiên

        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.crops_dir.mkdir(parents=True, exist_ok=True)

        self.monitor = dict(_sct().monitors[monitor_index])
        if region:
            left, top, width, height = region
            self.area = {"left": left, "top": top, "width": width, "height": height}
        else:
            self.area = {k: self.monitor[k] for k in ("left", "top", "width", "height")}
        self.t0 = time.time()

    # ---------- chụp & cắt ----------

    def _grab(self) -> np.ndarray:
        """Ảnh BGR của vùng đang theo dõi + cập nhật tỉ lệ scale thực tế."""
        shot = _sct().grab(self.area)
        frame = cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)
        # Retina (macOS) / DPI scaling (Windows): ảnh chụp lớn hơn vùng chụp tính
        # theo toạ độ chuột. Đo trực tiếp thay vì hỏi OS → đúng cho mọi nền tảng.
        self.scale = (
            frame.shape[1] / self.area["width"],
            frame.shape[0] / self.area["height"],
        )
        return frame

    def _crop_box(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        """Ô cắt quanh (x, y) theo toạ độ ảnh, đã nhân scale và kẹp trong biên."""
        cw = min(w, round(self.crop_w * self.scale[0]))
        ch = min(h, round(self.crop_h * self.scale[1]))
        x1 = max(0, min(x - cw // 2, w - cw))
        y1 = max(0, min(y - ch // 2, h - ch))
        return x1, y1, x1 + cw, y1 + ch

    def _capture(self, x_abs: int, y_abs: int, kind: str, button: str | None) -> dict | None:
        """Lưu frame (+ crop nếu là click) và trả về bản ghi sự kiện."""
        frame = self._grab()
        h, w = frame.shape[:2]

        # pynput trả toạ độ logic trên virtual desktop → đổi sang pixel trong ảnh.
        x = round((x_abs - self.area["left"]) * self.scale[0])
        y = round((y_abs - self.area["top"]) * self.scale[1])

        with self.lock:
            n = len(self.events)

        event: dict = {
            "index": n,
            "type": kind,
            "t": round(time.time() - self.t0, 3),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "x_abs": x_abs,  # toạ độ chuột (logic) — dùng để click lại
            "y_abs": y_abs,
            "x": x,  # toạ độ pixel trong ảnh — dùng để cắt/khớp template
            "y": y,
            "button": button,
            "label": None,  # điền ở giai đoạn chuẩn hoá
        }

        frame_path = self.frames_dir / f"frame_{n:03d}.png"
        cv2.imwrite(str(frame_path), frame)
        event["frame"] = str(frame_path.relative_to(self.out_dir).as_posix())

        if kind == "click":
            if not (0 <= x < w and 0 <= y < h):
                print(f"  ! click ({x_abs},{y_abs}) ngoài vùng chụp, bỏ crop")
            else:
                x1, y1, x2, y2 = self._crop_box(x, y, w, h)
                crop_path = self.crops_dir / f"crop_{n:03d}.png"
                cv2.imwrite(str(crop_path), frame[y1:y2, x1:x2])
                event["crop"] = str(crop_path.relative_to(self.out_dir).as_posix())
                event["crop_box"] = [x1, y1, x2, y2]

        with self.lock:
            self.events.append(event)
        self._flush()
        return event

    def _flush(self) -> None:
        """Ghi clicks.json sau mỗi sự kiện để không mất dữ liệu nếu crash."""
        with self.lock:
            data = {
                "platform": platform.system(),
                "monitor_index": self.monitor_index,
                "monitor": self.monitor,
                "capture_area": self.area,
                "scale": [round(self.scale[0], 4), round(self.scale[1], 4)],
                "crop_size": [self.crop_w, self.crop_h],
                "started_at": datetime.fromtimestamp(self.t0).isoformat(timespec="seconds"),
                "events": list(self.events),
            }
        tmp = self.out_dir / "clicks.json.tmp"
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.out_dir / "clicks.json")

    # ---------- callbacks ----------

    def on_click(self, x: int, y: int, button: mouse.Button, pressed: bool) -> None:
        if not pressed or not self.recording:
            return
        try:
            ev = self._capture(int(x), int(y), "click", button.name)
        except Exception as exc:  # listener chết lặng nếu callback ném ra ngoài
            print(f"  ! lỗi khi ghi click: {exc}")
            return
        if ev:
            print(f"[{ev['index']:03d}] click {button.name} @ ({x},{y})  t={ev['t']}s")

    def on_press(self, key) -> bool | None:
        name = key_name(key)
        if name == self.keys["start"]:
            self.recording = not self.recording
            print("=== BẮT ĐẦU GHI ===" if self.recording else "=== TẠM DỪNG GHI ===")
        elif name == self.keys["snap"]:
            if not self.recording:
                print(f"  ({self.keys['snap'].upper()} bị bỏ qua: chưa bật ghi)")
                return None
            pos = mouse.Controller().position
            try:
                ev = self._capture(int(pos[0]), int(pos[1]), "snapshot", None)
            except Exception as exc:
                print(f"  ! lỗi khi chụp snapshot: {exc}")
                return None
            if ev:
                print(f"[{ev['index']:03d}] snapshot (không click)  t={ev['t']}s")
        elif name == self.keys["quit"]:
            self.recording = False
            self.stop_flag.set()
            return False
        return None

    # ---------- vòng chạy ----------

    def run(self) -> int:
        k = self.keys
        print(f"Nền tảng: {platform.system()}   monitor {self.monitor_index}: {self.monitor}")
        print(f"Vùng chụp: {self.area}")
        print(f"Output: {self.out_dir}   crop: {self.crop_w}x{self.crop_h} (theo toạ độ chuột)")
        print(
            f"{k['start'].upper()} = bật/tắt ghi | {k['snap'].upper()} = chụp frame "
            f"(popup under attack) | {k['quit'].upper()} = thoát"
        )
        if IS_MAC:
            print(
                "macOS: Terminal cần quyền Accessibility (bắt phím/chuột) và Screen Recording\n"
                "       (System Settings → Privacy & Security). Nếu F8/F9 không ăn, bật\n"
                "       'Use F1, F2, etc. keys as standard function keys' hoặc dùng --start-key."
            )
        print("Thao tác đúng MỘT chu trình rally: Search → chọn team → March → chờ under attack.\n")

        try:
            probe = self._grab()
        except Exception as exc:
            print(f"Không chụp được màn hình: {exc}", file=sys.stderr)
            if IS_MAC:
                print("→ Cấp quyền Screen Recording cho Terminal rồi mở lại.", file=sys.stderr)
            return 1
        if self.scale != (1.0, 1.0):
            print(
                f"Scale phát hiện: {self.scale[0]:.2f}x{self.scale[1]:.2f} "
                f"(ảnh {probe.shape[1]}x{probe.shape[0]} px / vùng "
                f"{self.area['width']}x{self.area['height']} điểm)\n"
            )

        mouse_listener = mouse.Listener(on_click=self.on_click)
        mouse_listener.start()
        try:
            with keyboard.Listener(on_press=self.on_press) as kb:
                kb.join()
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            print(f"Listener lỗi: {exc}", file=sys.stderr)
            if IS_MAC:
                print("→ Cấp quyền Accessibility cho Terminal rồi mở lại.", file=sys.stderr)
            return 1
        finally:
            mouse_listener.stop()
            self._flush()

        n_click = sum(1 for e in self.events if e["type"] == "click")
        n_snap = len(self.events) - n_click
        print(f"\nĐã ghi {n_click} click + {n_snap} snapshot → {self.out_dir / 'clicks.json'}")
        if not self.events:
            print(f"Không có sự kiện nào — nhớ nhấn {k['start'].upper()} để bật ghi trước.")
        return 0


def pick_region(snap_key: str, quit_key: str) -> int:
    """Đo toạ độ cửa sổ giả lập: đưa chuột tới 2 góc, mỗi góc nhấn phím snap."""
    corners: list[tuple[int, int]] = []
    print(
        f"Đưa chuột tới GÓC TRÊN-TRÁI của cửa sổ giả lập rồi nhấn {snap_key.upper()}, "
        f"sau đó tới GÓC DƯỚI-PHẢI và nhấn {snap_key.upper()}. {quit_key.upper()} = huỷ."
    )

    def on_press(key) -> bool | None:
        name = key_name(key)
        if name == quit_key:
            return False
        if name != snap_key:
            return None
        pos = mouse.Controller().position
        corners.append((int(pos[0]), int(pos[1])))
        print(f"  góc {len(corners)}: {corners[-1]}")
        return None if len(corners) < 2 else False

    with keyboard.Listener(on_press=on_press) as kb:
        kb.join()

    if len(corners) < 2:
        print("Đã huỷ.")
        return 1
    (x1, y1), (x2, y2) = corners
    left, top = min(x1, x2), min(y1, y2)
    w, h = abs(x2 - x1), abs(y2 - y1)
    if w < 2 or h < 2:
        print("Vùng quá nhỏ, thử lại.", file=sys.stderr)
        return 1
    print(f"\n→ python recorder.py --region {left},{top},{w},{h}")
    return 0


def parse_crop(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        w, h = int(w), int(h)
        if w <= 0 or h <= 0:
            raise ValueError
        return w, h
    except ValueError:
        raise argparse.ArgumentTypeError("dạng WxH với số dương, ví dụ 120x60") from None


def parse_region(value: str) -> tuple[int, int, int, int]:
    try:
        parts = [int(p) for p in value.split(",")]
        if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
            raise ValueError
        return parts[0], parts[1], parts[2], parts[3]
    except ValueError:
        raise argparse.ArgumentTypeError("dạng x,y,w,h với w/h dương, ví dụ 100,80,900,1600") from None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DWauto recorder — ghi click + screenshot + crop mẫu")
    p.add_argument("--out", default="recordings", help="thư mục output (mặc định: recordings)")
    p.add_argument(
        "--crop",
        type=parse_crop,
        default=DEFAULT_CROP,
        metavar="WxH",
        help="ô cắt quanh con trỏ, tính theo toạ độ chuột (mặc định: 120x60)",
    )
    p.add_argument(
        "--monitor",
        type=int,
        default=1,
        help="chỉ số monitor của mss (1 = màn hình chính, 0 = toàn bộ)",
    )
    p.add_argument(
        "--region",
        type=parse_region,
        metavar="X,Y,W,H",
        help="chỉ chụp một vùng (cửa sổ BlueStacks / app game) thay vì cả màn hình",
    )
    p.add_argument(
        "--pick-region",
        action="store_true",
        help="đo toạ độ cửa sổ bằng chuột rồi in ra chuỗi --region tương ứng",
    )
    p.add_argument("--start-key", default="f8", help="phím bật/tắt ghi (mặc định: f8)")
    p.add_argument("--snap-key", default="f9", help="phím chụp frame rời (mặc định: f9)")
    p.add_argument("--quit-key", default="esc", help="phím thoát (mặc định: esc)")
    args = p.parse_args(argv)

    with _MSS() as sct:
        if not 0 <= args.monitor < len(sct.monitors):
            print(f"--monitor phải trong khoảng 0..{len(sct.monitors) - 1}", file=sys.stderr)
            return 2

    keys = {
        "start": args.start_key.lower(),
        "snap": args.snap_key.lower(),
        "quit": args.quit_key.lower(),
    }
    if len(set(keys.values())) != 3:
        print("--start-key / --snap-key / --quit-key phải khác nhau", file=sys.stderr)
        return 2

    if args.pick_region:
        return pick_region(keys["snap"], keys["quit"])

    out_dir = Path(args.out).expanduser().resolve()
    if (out_dir / "clicks.json").exists():
        print(f"Cảnh báo: {out_dir} đã có dữ liệu ghi cũ và sẽ bị ghi đè.")

    return Recorder(out_dir, args.crop, args.monitor, args.region, keys).run()


if __name__ == "__main__":
    raise SystemExit(main())
