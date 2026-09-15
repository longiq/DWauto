"""Kiểm tra membership qua server trước khi cho chạy — bắt buộc hỏi server mỗi
lần mở, KHÔNG tự tính bằng ngày lưu cục bộ trên máy như MuMu Player từng làm
(chính hạn chế đó là lý do người dùng không thể tự verify được lúc quyết định
đổi sang BlueStacks — xem SPEC.md/project_dwauto memory). Ngày bắt đầu trial 7
ngày do SERVER ghi nhận lúc lần đầu thấy device_id, không phải đồng hồ máy
khách, nên đổi giờ hệ thống không có tác dụng.

Có 1 khoảng ân hạn ngắn (24h) khi mất mạng tạm thời, dựa trên kết quả HỢP LỆ
gần nhất server đã trả — không phải để bỏ qua việc xác thực, chỉ để không làm
gián đoạn người đang dùng hợp lệ vì sự cố mạng thoáng qua.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

LICENSE_SERVER = "https://dw.longiq.xyz"
GRACE_SECONDS = 24 * 3600
STATE_FILE = Path.home() / ".dwauto" / "license.json"

# TẠM THỜI TẮT (16/09/2026): PayPal Subscriptions chưa có credential thật, tính
# năng bán membership chưa hoàn thiện — đổi thành True khi quay lại làm tiếp
# và sẵn sàng bật thu phí thật. Khi False, check() bỏ qua hẳn việc gọi server.
ENABLED = False


class LicenseError(Exception):
    """Không được phép chạy — kèm activate_url để dẫn người dùng đi kích hoạt."""

    def __init__(self, message: str, activate_url: str | None = None):
        super().__init__(message)
        self.activate_url = activate_url


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def device_id() -> str:
    """Định danh máy này — sinh 1 lần, lưu cục bộ, gửi kèm mọi lần hỏi server."""
    state = _load_state()
    if "device_id" not in state:
        state["device_id"] = uuid.uuid4().hex
        _save_state(state)
    return state["device_id"]


def _fetch_status(dev_id: str) -> dict:
    """User-Agent mặc định của urllib ("Python-urllib/x.y") bị Cloudflare chặn
    thẳng 403 trước khi tới được server — phải giả User-Agent trình duyệt."""
    url = f"{LICENSE_SERVER}/api/license/status?device_id={dev_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "DWauto/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())


_MESSAGES = {
    "expired": "Bản dùng thử 7 ngày đã hết hạn.",
    "cancelled": "Membership đã bị huỷ.",
    "suspended": "Thanh toán bị từ chối, membership đang tạm khoá.",
    "approval_pending": "Đăng ký PayPal chưa hoàn tất.",
}


def check() -> dict:
    """Trả {'status', 'days_left', 'offline'} nếu được phép chạy.

    Ném LicenseError (có .activate_url) nếu không được phép — gọi nơi khởi
    động chương trình (main.py / app.py), trước khi làm bất cứ việc gì khác.
    """
    if not ENABLED:
        return {"status": "active", "days_left": None, "offline": False}

    dev_id = device_id()
    state = _load_state()
    try:
        result = _fetch_status(dev_id)
    except (urllib.error.URLError, OSError, ValueError):
        last = state.get("last_ok")
        if last and time.time() - last.get("ts", 0) < GRACE_SECONDS and last.get("status") in ("trial", "active"):
            return {"status": last["status"], "days_left": last.get("days_left"), "offline": True}
        raise LicenseError(
            "Không kết nối được tới server để xác thực membership. Kiểm tra mạng rồi thử lại.",
            activate_url=f"{LICENSE_SERVER}/activate.html?device_id={dev_id}",
        )

    status = result.get("status")
    if status in ("trial", "active"):
        state["last_ok"] = {"ts": time.time(), "status": status, "days_left": result.get("days_left")}
        _save_state(state)
        return {"status": status, "days_left": result.get("days_left"), "offline": False}

    activate_url = result.get("activate_url") or f"{LICENSE_SERVER}/activate.html?device_id={dev_id}"
    raise LicenseError(
        _MESSAGES.get(status, f"Không thể sử dụng (trạng thái: {status})."),
        activate_url=activate_url,
    )
