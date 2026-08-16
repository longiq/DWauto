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

from dwauto.actions import AdbMouse, Mouse
from dwauto.config import Config, ConfigError, load_config
from dwauto.rally import STEPS, RallyRunner
from dwauto.screen import Screen


def make_screen(cfg: Config):
    """Nguồn ảnh theo config: ADB (cửa sổ ở đâu cũng chạy) hoặc chụp màn hình."""
    if cfg.backend == "screen":
        logging.info("Capture source: screen grab, fixed region %s", cfg.region)
        return Screen(area=dict(cfg.region))

    from dwauto.adb import AdbScreen, scan_ports
    from dwauto.window import find_window

    port = cfg.adb_port
    if port == 0:
        port = scan_ports(cfg.adb_host)
        if port is None:
            raise RuntimeError(
                "No open ADB port found. Start the emulator, and enable ADB under "
                "Settings > Advanced if you are on BlueStacks for Windows."
            )
        logging.info("Found ADB port: %d", port)

    scr = AdbScreen(
        template_width=cfg.template_width,
        host=cfg.adb_host,
        port=port,
        window_title=cfg.window_title,
        adb_binary=cfg.adb_binary,
    )
    raw = scr.grab_raw()  # thất bại sớm nếu ADB không dùng được
    try:
        win = find_window(cfg.window_title)
        where = f"window '{cfg.window_title}' at ({win.left},{win.top}) {win.width}x{win.height}"
    except Exception:
        # click.backend=adb không cần vị trí cửa sổ — cửa sổ thu nhỏ/bị che vẫn
        # chụp và tap được bình thường qua ADB, chỉ mất thông tin log ở đây.
        where = f"window '{cfg.window_title}' not found (minimized/hidden — fine for click.backend=adb)"
    logging.info(
        "Capture source: ADB %s:%d - Android screen %dx%d, %s",
        cfg.adb_host, port, raw.shape[1], raw.shape[0], where,
    )
    return scr


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
        log.info("--- scan %d/%d (image %dx%d) ---", i + 1, rounds, frame.shape[1], frame.shape[0])
        for name in names:
            need = cfg.threshold_for(name)
            m = screen.find(str(cfg.templates[name]), threshold=need, screen=frame)
            if m is None:
                loose = screen.find(str(cfg.templates[name]), threshold=0.0, screen=frame)
                log.info("  %-15s not found (best score %.2f < %.2f)",
                         name, loose.score if loose else 0.0, need)
                continue
            seen_any = True
            if getattr(mouse, "uses_device_coords", False):
                mx, my = screen.to_device(m.x, m.y)
                kind = "tap"
            else:
                mx, my = screen.to_mouse(m.x, m.y)
                kind = "click"
            log.info("  %-15s FOUND score %.2f at image (%d,%d) -> would %s at (%d,%d)",
                     name, m.score, m.x, m.y, kind, mx, my)
        if i < rounds - 1:
            time.sleep(1.0)

    if not seen_any:
        log.error(
            "No button recognised. Check that the emulator window is not covered, and "
            "that the settings in %s still match your setup.",
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
                    logging.info("=== PAUSED (press %s to resume) ===", self.start_key.upper())
                else:
                    self.running.set()
                    logging.info("=== RUNNING ===")
            elif name == self.quit_key:
                logging.info("=== QUIT ===")
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
    p.add_argument(
        "--marches",
        type=int,
        default=0,
        help="chạy ngay N lượt march rồi thoát (không cần phím tắt) — dùng để chạy thử",
    )
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

    try:
        screen = make_screen(cfg)
    except Exception as exc:
        print(f"Không mở được nguồn ảnh: {exc}", file=sys.stderr)
        return 2

    if cfg.click_backend == "adb":
        if not cfg.adb_binary:
            print("Lỗi config: click.backend=adb cần khai 'capture.adb_binary'", file=sys.stderr)
            return 2
        mouse = AdbMouse(
            adb_binary=cfg.adb_binary,
            host=cfg.adb_host,
            port=screen.port if hasattr(screen, "port") else cfg.adb_port,
            offset_px=cfg.offset_px,
            delay=cfg.click_delay,
            dry_run=args.dry_run,
        )
        logging.info("Click backend: ADB tap (%s) — cửa sổ bị che/thu nhỏ vẫn chạy được.", cfg.adb_binary)
    else:
        mouse = Mouse(
            offset_px=cfg.offset_px,
            delay=cfg.click_delay,
            move_duration=cfg.move_duration,
            dry_run=args.dry_run,
        )

    logging.info(
        "%d marches per cycle, %g minute wait between cycles, match threshold %.2f",
        cfg.marches_per_round, cfg.wait_minutes, cfg.threshold,
    )

    if args.dry_run:
        with screen:
            return dry_run(cfg, screen, mouse)

    if getattr(mouse, "uses_device_coords", False):
        # AdbMouse tap thẳng vào Android qua ADB — không cần cửa sổ hiện/focus.
        def focus() -> bool:
            return True
    else:
        from dwauto.window import focus_window

        def focus() -> bool:
            return focus_window(cfg.window_title)

    if args.marches > 0:
        runner = RallyRunner(screen, mouse, cfg, focus=focus)
        logging.info("Test run: %d marches, starting now.", args.marches)
        try:
            for i in range(args.marches):
                logging.info("--- Lượt %d/%d ---", i + 1, args.marches)
                if not runner.march_once() and not runner.recover():
                    break
        finally:
            screen.close()
            logging.info(
                "Summary: %d marches succeeded, %d failed",
                runner.marches_done, runner.marches_failed,
            )
        return 0 if runner.marches_done == args.marches else 1

    hotkeys = HotkeyControl(args.start_key.lower(), args.quit_key.lower())
    hotkeys.start()
    runner = RallyRunner(screen, mouse, cfg, should_stop=hotkeys.should_stop, focus=focus)

    logging.info(
        "Ready. %s = run/pause, %s = quit. Bring the emulator to front, then press %s.",
        args.start_key.upper(), args.quit_key.upper(), args.start_key.upper(),
    )
    try:
        while not hotkeys.quitting.is_set():
            if not hotkeys.running.is_set():
                time.sleep(0.2)
                continue
            runner.run_forever()
    except KeyboardInterrupt:
        logging.info("Stopped by Ctrl-C")
    except Exception:
        logging.exception("Unexpected error - stopping for safety")
        return 1
    finally:
        hotkeys.stop()
        screen.close()
        logging.info(
            "Summary: %d marches succeeded, %d failed",
            runner.marches_done, runner.marches_failed,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
