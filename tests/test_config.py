"""Test đọc/kiểm config — sai config phải chết sớm với thông báo rõ ràng."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dwauto.config import ConfigError, load_config

REPO = Path(__file__).resolve().parent.parent

BASE = {
    "capture": {"region": [149, 84, 506, 932]},
    "match": {"threshold": 0.85},
    "templates": {
        "search_button": "a.png",
        "search_confirm": "b.png",
        "rally_button": "c.png",
        "march_button": "d.png",
    },
    "rally": {"marches_per_round": 3, "wait_minutes": 5},
    "timing": {"step_timeout": 8.0, "poll_interval": 0.4, "retries": 2, "click_delay": [0.3, 0.9]},
    "click": {"offset_px": 4, "move_duration": [0.08, 0.2]},
}


def write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def deep(**overrides) -> dict:
    """Bản sao BASE với vài mục con bị ghi đè."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in BASE.items()}
    for section, patch in overrides.items():
        if patch is None:
            out.pop(section, None)
        else:
            out[section] = {**out.get(section, {}), **patch}
    return out


def test_config_that_cua_repo_hop_le():
    """config.yaml thật trong repo phải load được và trỏ đúng template có sẵn."""
    cfg = load_config(REPO / "config.yaml")
    assert cfg.region == {"left": 149, "top": 84, "width": 506, "height": 932}
    assert cfg.marches_per_round == 3
    assert cfg.wait_seconds == cfg.wait_minutes * 60
    assert set(cfg.templates) >= {"search_button", "search_confirm", "rally_button", "march_button"}
    for p in cfg.templates.values():
        assert p.is_file()


def test_load_va_ep_kieu(tmp_path):
    cfg = load_config(write(tmp_path, BASE), check_templates=False)
    assert cfg.threshold == 0.85
    assert cfg.click_delay == (0.3, 0.9)
    assert cfg.retries == 2
    assert cfg.templates["search_button"] == tmp_path / "a.png"  # tương đối theo file config


def test_thieu_file(tmp_path):
    with pytest.raises(ConfigError, match="Không tìm thấy config"):
        load_config(tmp_path / "khong_co.yaml")


def test_yaml_hong(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("capture: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_config(p)


def test_thieu_template_bi_bao(tmp_path):
    data = deep()
    data["templates"] = {"search_button": "a.png"}
    with pytest.raises(ConfigError, match="rally_button"):
        load_config(write(tmp_path, data), check_templates=False)


def test_template_khong_ton_tai(tmp_path):
    with pytest.raises(ConfigError, match="không tồn tại"):
        load_config(write(tmp_path, BASE), check_templates=True)


@pytest.mark.parametrize("section", ["capture", "match", "templates", "rally", "timing"])
def test_thieu_muc_bat_buoc(tmp_path, section):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, deep(**{section: None})), check_templates=False)


@pytest.mark.parametrize("threshold", [0.0, -0.1, 1.5])
def test_nguong_ngoai_khoang(tmp_path, threshold):
    with pytest.raises(ConfigError, match="threshold"):
        load_config(write(tmp_path, deep(match={"threshold": threshold})), check_templates=False)


@pytest.mark.parametrize("region", [[1, 2, 3], [0, 0, 0, 100], [0, 0, 100, -5]])
def test_region_sai(tmp_path, region):
    with pytest.raises(ConfigError, match="region"):
        load_config(write(tmp_path, deep(capture={"region": region})), check_templates=False)


def test_so_am_bi_chan(tmp_path):
    with pytest.raises(ConfigError, match="retries"):
        load_config(write(tmp_path, deep(timing={"retries": -1})), check_templates=False)
    with pytest.raises(ConfigError, match="wait_minutes"):
        load_config(write(tmp_path, deep(rally={"wait_minutes": -1})), check_templates=False)
    with pytest.raises(ConfigError, match="marches_per_round"):
        load_config(write(tmp_path, deep(rally={"marches_per_round": 0})), check_templates=False)


def test_khoang_delay_sai(tmp_path):
    with pytest.raises(ConfigError, match="click_delay"):
        load_config(write(tmp_path, deep(timing={"click_delay": [0.9, 0.3]})), check_templates=False)


def test_wait_minutes_0_van_hop_le(tmp_path):
    cfg = load_config(write(tmp_path, deep(rally={"wait_minutes": 0})), check_templates=False)
    assert cfg.wait_seconds == 0
