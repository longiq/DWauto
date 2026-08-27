"""Test phần logic thuần của dwauto.license — không gọi mạng thật (dùng
monkeypatch cho _fetch_status). Mục tiêu: state file + xử lý các trạng thái
server trả về, và cơ chế ân hạn khi mất mạng."""

from __future__ import annotations

import json
import time

import pytest

from dwauto import license as lic


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(lic, "STATE_FILE", tmp_path / "license.json")
    yield


def test_device_id_stable_across_calls():
    first = lic.device_id()
    second = lic.device_id()
    assert first == second
    assert len(first) == 32  # uuid4().hex


def test_check_trial_ok(monkeypatch):
    monkeypatch.setattr(lic, "_fetch_status", lambda dev_id: {"status": "trial", "days_left": 5})
    result = lic.check()
    assert result == {"status": "trial", "days_left": 5, "offline": False}


def test_check_active_ok(monkeypatch):
    monkeypatch.setattr(lic, "_fetch_status", lambda dev_id: {"status": "active"})
    result = lic.check()
    assert result["status"] == "active"
    assert result["offline"] is False


def test_check_expired_raises_with_activate_url(monkeypatch):
    monkeypatch.setattr(
        lic, "_fetch_status",
        lambda dev_id: {"status": "expired", "activate_url": "https://dw.longiq.xyz/activate.html?device_id=x"},
    )
    with pytest.raises(lic.LicenseError) as exc_info:
        lic.check()
    assert exc_info.value.activate_url == "https://dw.longiq.xyz/activate.html?device_id=x"


def test_check_network_error_no_cache_raises(monkeypatch):
    def boom(dev_id):
        raise OSError("network down")

    monkeypatch.setattr(lic, "_fetch_status", boom)
    with pytest.raises(lic.LicenseError):
        lic.check()


def test_check_network_error_within_grace_uses_cache(monkeypatch):
    monkeypatch.setattr(lic, "_fetch_status", lambda dev_id: {"status": "trial", "days_left": 3})
    lic.check()  # ghi last_ok vào state file

    def boom(dev_id):
        raise OSError("network down")

    monkeypatch.setattr(lic, "_fetch_status", boom)
    result = lic.check()
    assert result == {"status": "trial", "days_left": 3, "offline": True}


def test_check_network_error_after_grace_expires_raises(monkeypatch):
    monkeypatch.setattr(lic, "_fetch_status", lambda dev_id: {"status": "active"})
    lic.check()

    state = json.loads(lic.STATE_FILE.read_text())
    state["last_ok"]["ts"] = time.time() - lic.GRACE_SECONDS - 1
    lic.STATE_FILE.write_text(json.dumps(state))

    def boom(dev_id):
        raise OSError("network down")

    monkeypatch.setattr(lic, "_fetch_status", boom)
    with pytest.raises(lic.LicenseError):
        lic.check()
