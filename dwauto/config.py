"""Đọc + kiểm tra config.yaml.

Kiểm sớm và báo lỗi cụ thể: sai config phát hiện lúc khởi động vẫn hơn là để tool
click nhầm chỗ giữa chừng.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REQUIRED_TEMPLATES = ("search_button", "search_confirm", "rally_button", "march_button")


class ConfigError(Exception):
    """Config thiếu khoá, sai kiểu, hoặc trỏ tới template không tồn tại."""


@dataclass
class Config:
    region: dict[str, int]
    threshold: float
    templates: dict[str, Path]
    marches_per_round: int
    wait_minutes: float
    step_timeout: float
    poll_interval: float
    retries: int
    click_delay: tuple[float, float]
    offset_px: int
    move_duration: tuple[float, float]
    path: Path = field(default=Path("config.yaml"))

    @property
    def wait_seconds(self) -> float:
        return self.wait_minutes * 60.0


def _get(d: dict, key: str, where: str):
    if key not in d:
        raise ConfigError(f"Thiếu '{key}' trong mục '{where}' của config")
    return d[key]


def _pair(value, where: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError(f"'{where}' phải là [min, max]")
    lo, hi = float(value[0]), float(value[1])
    if lo < 0 or hi < lo:
        raise ConfigError(f"'{where}' phải thoả 0 <= min <= max, đang là {list(value)}")
    return lo, hi


def _positive(value, where: str, kind=float):
    try:
        v = kind(value)
    except (TypeError, ValueError):
        raise ConfigError(f"'{where}' phải là số, đang là {value!r}") from None
    if v <= 0:
        raise ConfigError(f"'{where}' phải > 0, đang là {v}")
    return v


def load_config(path: str | Path = "config.yaml", check_templates: bool = True) -> Config:
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"Không tìm thấy config: {p}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config không phải YAML hợp lệ: {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"Config phải là một mapping, đang là {type(raw).__name__}")

    reg = _get(_get(raw, "capture", "config"), "region", "capture")
    if not isinstance(reg, (list, tuple)) or len(reg) != 4:
        raise ConfigError("'capture.region' phải là [left, top, width, height]")
    left, top, width, height = (int(v) for v in reg)
    if width <= 0 or height <= 0:
        raise ConfigError(f"'capture.region' có width/height không hợp lệ: {width}x{height}")

    threshold = float(_get(_get(raw, "match", "config"), "threshold", "match"))
    if not 0.0 < threshold <= 1.0:
        raise ConfigError(f"'match.threshold' phải trong (0, 1], đang là {threshold}")

    tpl_raw = _get(raw, "templates", "config")
    if not isinstance(tpl_raw, dict):
        raise ConfigError("'templates' phải là mapping tên → đường dẫn")
    missing = [n for n in REQUIRED_TEMPLATES if n not in tpl_raw]
    if missing:
        raise ConfigError(f"Thiếu template: {', '.join(missing)}")
    base = p.parent
    templates = {n: (base / str(v)) for n, v in tpl_raw.items()}
    if check_templates:
        absent = [f"{n} ({q})" for n, q in templates.items() if not q.is_file()]
        if absent:
            raise ConfigError("Template không tồn tại: " + "; ".join(absent))

    rally = _get(raw, "rally", "config")
    timing = _get(raw, "timing", "config")
    click = raw.get("click", {}) or {}

    retries = int(timing.get("retries", 2))
    if retries < 0:
        raise ConfigError(f"'timing.retries' không được âm, đang là {retries}")
    offset = int(click.get("offset_px", 0))
    if offset < 0:
        raise ConfigError(f"'click.offset_px' không được âm, đang là {offset}")

    wait_minutes = float(_get(rally, "wait_minutes", "rally"))
    if wait_minutes < 0:
        raise ConfigError(f"'rally.wait_minutes' không được âm, đang là {wait_minutes}")

    return Config(
        region={"left": left, "top": top, "width": width, "height": height},
        threshold=threshold,
        templates=templates,
        marches_per_round=int(_positive(_get(rally, "marches_per_round", "rally"),
                                        "rally.marches_per_round", int)),
        wait_minutes=wait_minutes,
        step_timeout=_positive(_get(timing, "step_timeout", "timing"), "timing.step_timeout"),
        poll_interval=_positive(_get(timing, "poll_interval", "timing"), "timing.poll_interval"),
        retries=retries,
        click_delay=_pair(timing.get("click_delay", [0.3, 0.8]), "timing.click_delay"),
        offset_px=offset,
        move_duration=_pair(click.get("move_duration", [0.08, 0.2]), "click.move_duration"),
        path=p,
    )
