"""CHẾ ĐỘ AUTO: vòng lặp rally + phím tắt Start/Stop + --dry-run.

    python main.py --dry-run     # chỉ báo thấy nút gì, ở đâu — KHÔNG click
    python main.py               # F8 để chạy/dừng, Esc để thoát

Chỉ giả lập input chuột. Kéo chuột lên góc trên-trái màn hình để dừng khẩn cấp
(pyautogui FAILSAFE).
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from dwauto.actions import Mouse
from dwauto.config import Config, ConfigError, load_config
from dwauto.rally import STEPS, RallyRunner
from dwauto.screen import Screen


def setup_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def dry_run(cfg: Config, screen: Screen, mouse: Mouse, rounds: int = 3) -> int:
    """Quét từng template trên màn hình hiện tại, báo thấy gì và sẽ click ở đâu.

    Không đi theo chuỗi bước như chạy thật, vì dry-run không click nên màn hình
    không bao giờ chuyển sang bước kế.
    """
    log = logging.getLogger("dry-run")
    names = [s.template for s in STEPS]
    seen_any = False
    for i in range(rounds):
        frame = screen.capture()
        log.info("--- quét %d/%d (ảnh %dx%d, scale %.2f) ---",
                 i + 1, rounds, frame.shape[1], frame.shape[0], screen.scale[0])
        for name in names:
            m = screen.find(str(cfg.templates[name]), threshold=cfg.threshold, screen=frame)
            if m is None:
                loose = screen.find(str(cfg.templates[name]), threshold=0.0, screen=frame)
                log.info("  %-15s không thấy (điểm cao nhất %.2f < %.2f)",
                         name, loose.score if loose else 0.0, cfg.threshold)
                continue
            seen_any = True
            mx, my = screen.to_mouse(m.x, m.y)
            log.info("  %-15s THẤY điểm %.2f tại ảnh (%d,%d) → sẽ click ở (%d,%d)",
                     name, m.score, m.x, m.y, mx, my)
        if i < rounds - 1:
            time.sleep(1.0)

    if not seen_any:
        log.error(
            "Không nhận ra nút nào. Kiểm tra: cửa sổ giả lập có bị che không, "
            "capture.region trong %s còn đúng không (đo lại: python recorder.py --pick-region).",
            cfg.path,
        )
        return 1
    return 0


class HotkeyControl:
    """F8 chạy/dừng, Esc thoát. Đọc được từ mọi cửa sổ nên không cần focus Terminal."""

    def __init__(self, start_key: str = "f8", quit_key: str = "esc"):
        self.start_key = start_key
        self.quit_key = quit_key
        self.running = threading.Event()
        self.quitting = threading.Event()
        self._listener = None

    def start(self) -> None:
        from pynput import keyboard

        def key_name(key) -> str | None:
            name = getattr(key, "name", None)
            if name:
                return name.lower()
            char = getattr(key, "char", None)
            return char.lower() if char else None

        def on_press(key):
            name = key_name(key)
            if name == self.start_key:
                if self.running.is_set():
                    self.running.clear()
                    logging.info("=== TẠM DỪNG (bấm %s để chạy tiếp) ===", self.start_key.upper())
                else:
                    self.running.set()
                    logging.info("=== CHẠY ===")
            elif name == self.quit_key:
                logging.info("=== THOÁT ===")
                self.quitting.set()
                self.running.clear()
                return False
            return None

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    def should_stop(self) -> bool:
        return self.quitting.is_set() or not self.running.is_set()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DWauto — auto rally cho Darkwar Survival")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--dry-run", action="store_true", help="chỉ báo nhận diện nút, không click")
    p.add_argument("--log-file", default="dwauto.log", help="'' để tắt ghi log ra file")
    p.add_argument("--start-key", default="f8")
    p.add_argument("--quit-key", default="esc")
    args = p.parse_args(argv)

    setup_logging(Path(args.log_file) if args.log_file else None)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Lỗi config: {exc}", file=sys.stderr)
        return 2

    screen = Screen(area=dict(cfg.region))
    mouse = Mouse(
        offset_px=cfg.offset_px,
        delay=cfg.click_delay,
        move_duration=cfg.move_duration,
        dry_run=args.dry_run,
    )

    logging.info("Vùng chụp: %s", cfg.region)
    logging.info(
        "%d lượt/vòng, chờ %g phút giữa các vòng, ngưỡng khớp %.2f",
        cfg.marches_per_round, cfg.wait_minutes, cfg.threshold,
    )

    if args.dry_run:
        with screen:
            return dry_run(cfg, screen, mouse)

    hotkeys = HotkeyControl(args.start_key.lower(), args.quit_key.lower())
    hotkeys.start()
    runner = RallyRunner(screen, mouse, cfg, should_stop=hotkeys.should_stop)

    logging.info(
        "Sẵn sàng. %s = chạy/dừng, %s = thoát. Đưa BlueStacks lên trước rồi bấm %s.",
        args.start_key.upper(), args.quit_key.upper(), args.start_key.upper(),
    )
    try:
        while not hotkeys.quitting.is_set():
            if not hotkeys.running.is_set():
                time.sleep(0.2)
                continue
            runner.run_forever()
    except KeyboardInterrupt:
        logging.info("Dừng bởi Ctrl-C")
    except Exception:
        logging.exception("Lỗi không lường trước — dừng lại cho an toàn")
        return 1
    finally:
        hotkeys.stop()
        screen.close()
        logging.info(
            "Tổng kết: %d lượt thành công, %d lượt hỏng",
            runner.marches_done, runner.marches_failed,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
