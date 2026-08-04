"""Build a standalone bundle — the friend who receives it installs nothing.

    python build.py

Produces dist/DWauto.app (macOS) or dist/DWauto/ (Windows). Python, Tk, OpenCV and
the templates all ship inside; no interpreter is needed on the target machine.

Note: bundles are not cross-compilable — build the Windows executable on Windows.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "DWauto"
SEP = ";" if platform.system() == "Windows" else ":"

HIDDEN = [
    "main",
    "dwauto.actions",
    "dwauto.adb",
    "dwauto.config",
    "dwauto.rally",
    "dwauto.screen",
    "dwauto.window",
]


def main() -> int:
    for stale in (ROOT / "build", ROOT / "dist", ROOT / f"{NAME}.spec"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        "--add-data", f"{ROOT / 'config.yaml'}{SEP}.",
        "--add-data", f"{ROOT / 'templates'}{SEP}templates",
        "--osx-bundle-identifier", "com.longiq.dwauto",
    ]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]
    cmd.append(str(ROOT / "app.py"))

    print(" ".join(cmd), "\n")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    out = ROOT / "dist" / (f"{NAME}.app" if platform.system() == "Darwin" else NAME)
    seen, size = set(), 0  # bundle dùng hard link, phải lọc trùng inode kẻo cộng gấp đôi
    for f in out.rglob("*"):
        if f.is_file() and not f.is_symlink():
            st = f.stat()
            if st.st_ino not in seen:
                seen.add(st.st_ino)
                size += st.st_size
    size /= 1e6
    print(f"\nĐóng gói xong: {out}  ({size:.0f} MB)")
    if platform.system() == "Darwin":
        print(
            "Gửi cho bạn bè: nén .app thành .zip trước khi gửi (giữ nguyên quyền thực thi).\n"
            "Lần đầu mở phải CHUỘT PHẢI → Open, vì app chưa ký số."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
