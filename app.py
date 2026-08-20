"""DWauto desktop app — GUI wrapper around the rally loop.

Run from source:   python app.py
Build a bundle:    python build.py
"""

from __future__ import annotations

import dataclasses
import logging
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

APP_NAME = "DWauto"


def log_path() -> Path:
    """Nơi ghi log đầy đủ — trong bundle .app thì không ghi cạnh file thực thi được."""
    mac_logs = Path.home() / "Library" / "Logs"
    return (mac_logs if mac_logs.is_dir() else Path.home()) / "DWauto.log"


def resource_dir() -> Path:
    """Where config.yaml and templates/ live — differs once PyInstaller bundles us."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def accessibility_ok(prompt: bool = False) -> bool:
    """macOS only: are we allowed to control the mouse?

    macOS never lets an app grant itself this permission. With prompt=True we can
    at least raise the system dialog that deep-links into System Settings, so the
    user gets one guided click instead of hunting through preferences.
    """
    if sys.platform != "darwin":
        return True
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))
    except Exception:
        return True  # can't tell — let the run proceed and fail loudly instead


class QueueLogHandler(logging.Handler):
    """Ship log records to the UI thread; tkinter must not be touched from workers."""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.queue = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait((record.levelno, self.format(record)))
        except queue.Full:
            pass


class RallyWorker(threading.Thread):
    """Runs the rally loop off the UI thread so the window stays responsive."""

    def __init__(self, minutes: float, on_finish):
        super().__init__(daemon=True)
        self.minutes = minutes
        self.on_finish = on_finish
        self.stop_event = threading.Event()
        self.error: str | None = None

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        log = logging.getLogger("app")
        screen = None
        try:
            from dwauto.actions import AdbMouse, Mouse
            from dwauto.config import load_config
            from dwauto.rally import RallyRunner
            from main import make_screen

            cfg = load_config(resource_dir() / "config.yaml")
            cfg = dataclasses.replace(cfg, wait_minutes=self.minutes)

            screen = make_screen(cfg)
            if cfg.click_backend == "adb":
                mouse = AdbMouse(
                    adb_binary=cfg.adb_binary,
                    host=cfg.adb_host,
                    port=getattr(screen, "port", cfg.adb_port),
                    serial=getattr(screen, "serial", None),
                    offset_px=cfg.offset_px,
                    delay=cfg.click_delay,
                )
            else:
                mouse = Mouse(
                    offset_px=cfg.offset_px,
                    delay=cfg.click_delay,
                    move_duration=cfg.move_duration,
                )

            if getattr(mouse, "uses_device_coords", False):
                focus = lambda: True  # noqa: E731 — AdbMouse không cần cửa sổ hiện/focus
            else:
                from dwauto.window import focus_window

                focus = lambda: focus_window(cfg.window_title)  # noqa: E731

            runner = RallyRunner(
                screen, mouse, cfg,
                should_stop=self.stop_event.is_set,
                focus=focus,
            )
            log.info(
                "Started — %d marches per cycle, %g minute wait between cycles.",
                cfg.marches_per_round, self.minutes,
            )
            runner.run_forever()
            log.info(
                "Stopped. %d marches succeeded, %d failed.",
                runner.marches_done, runner.marches_failed,
            )
        except Exception as exc:  # noqa: BLE001 — surface anything to the user
            self.error = str(exc)
            log.error("%s", exc)
        finally:
            if screen is not None:
                try:
                    screen.close()
                except Exception:
                    pass
            self.on_finish()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.resizable(False, False)
        self.worker: RallyWorker | None = None
        self.log_queue: queue.Queue = queue.Queue(maxsize=1000)
        self._build_ui()
        self._install_logging()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, self._drain_log)

    # ---------- layout ----------

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        row = ttk.Frame(root)
        row.pack()
        ttk.Label(row, text="Cycle").pack(side="left")
        self.minutes_var = tk.StringVar(value="3")
        self.minutes_entry = ttk.Entry(row, width=4, textvariable=self.minutes_var, justify="right")
        self.minutes_entry.pack(side="left", padx=6)
        ttk.Label(row, text="minutes").pack(side="left")

        self.toggle = ttk.Button(root, text="Start", command=self._toggle, width=14)
        self.toggle.pack(pady=(8, 4))

        # Một dòng trạng thái = tin nhắn log mới nhất. Log đầy đủ nằm ở file, để
        # cửa sổ gọn mà vẫn còn đường lần khi có lỗi.
        self.status_var = tk.StringVar(value="Idle")
        self.status = ttk.Label(root, textvariable=self.status_var, foreground="#888",
                                wraplength=210, justify="center")
        self.status.pack()

    def _install_logging(self) -> None:
        root = logging.getLogger()
        root.setLevel(logging.INFO)

        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(message)s"))  # ngắn, để vừa một dòng
        root.addHandler(handler)

        try:  # log đầy đủ ra file để còn lần được lỗi khi cửa sổ chỉ hiện một dòng
            file_handler = logging.FileHandler(log_path(), encoding="utf-8")
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
            )
            root.addHandler(file_handler)
        except OSError:
            pass

    # ---------- actions ----------

    def _read_minutes(self) -> float | None:
        raw = self.minutes_var.get().strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            self._set_status(f"'{raw}' is not a number.", error=True)
            return None
        if value < 0:
            self._set_status("Cycle interval cannot be negative.", error=True)
            return None
        if value > 24 * 60:
            self._set_status("Cycle interval must be under 24 hours.", error=True)
            return None
        return value

    def _toggle(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.worker.stop()
            self.toggle.config(text="Stopping…", state="disabled")
            self._set_status("Stopping after the current step…")
            return

        minutes = self._read_minutes()
        if minutes is None:
            return

        # AdbMouse tap qua ADB không đụng chuột thật — không cần quyền Accessibility.
        # Chỉ bắt buộc quyền này khi config còn dùng click.backend=mouse (BlueStacks...).
        from dwauto.config import ConfigError, load_config

        try:
            cfg = load_config(resource_dir() / "config.yaml", check_templates=False)
        except ConfigError as exc:
            self._set_status(f"Config error: {exc}", error=True)
            return
        needs_accessibility = cfg.click_backend != "adb"

        if needs_accessibility and not accessibility_ok():
            accessibility_ok(prompt=True)  # raises the macOS dialog with a settings link
            self._set_status(
                "Allow DWauto under Privacy & Security → Accessibility, then reopen the app.",
                error=True,
            )
            return
        self.worker = RallyWorker(minutes, on_finish=lambda: self.after(0, self._on_worker_done))
        self.worker.start()
        self.toggle.config(text="Stop")
        self.minutes_entry.config(state="disabled")
        self._set_status(
            "Running." if not needs_accessibility else "Running — keep the emulator window visible."
        )

    def _on_worker_done(self) -> None:
        error = self.worker.error if self.worker else None
        self.worker = None
        self.toggle.config(text="Start", state="normal")
        self.minutes_entry.config(state="normal")
        self._set_status(error or "Idle", error=bool(error))

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.worker.stop()
            self.worker.join(timeout=5)
        self.destroy()

    # ---------- output ----------

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_var.set(text)
        self.status.config(foreground="#c0392b" if error else "#777")

    def _drain_log(self) -> None:
        last = None
        while True:
            try:
                last = self.log_queue.get_nowait()
            except queue.Empty:
                break
        if last is not None and self.worker is not None:
            level, text = last
            self._set_status(text, error=level >= logging.WARNING)
        self.after(300, self._drain_log)


def main() -> int:
    if not getattr(sys, "frozen", False):
        # Chỉ cần khi chạy trực tiếp từ source (`python app.py`), để tìm thấy
        # package dwauto/ cạnh app.py. Khi đã đóng gói, dwauto đã nằm sẵn trong
        # PYZ frozen — chèn _MEIPASS vào sys.path lúc này khiến Python thấy cv2
        # ở CẢ bản frozen lẫn bản rời trên đĩa (do hook PyInstaller giải nén data
        # files của cv2 ra _MEIPASS), import 2 đường khác nhau → cv2 tự phát hiện
        # bị nạp đè và báo "recursion is detected during loading of cv2 binary
        # extensions". Bỏ hẳn dòng này khi frozen là cách sửa đúng gốc.
        sys.path.insert(0, str(resource_dir()))
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
