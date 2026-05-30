"""Unit tests for the LensConfig dataclass and env loader."""
from __future__ import annotations

import pytest

from autopsy.core.config import LensConfig, load_config_from_env


def test_default_values_match_spec():
    c = LensConfig()
    assert c.default_sample == "errors"
    assert c.flush_batch_size == 100
    assert c.flush_interval_ms == 50
    assert c.queue_maxsize == 10_000
    assert c.max_total_disk_mb == 2048
    assert c.max_session_age_days == 30
    assert c.max_in_flight_buffer_mb == 10
    assert c.max_event_field_bytes == 65_536
    assert c.log_finalization is True
    assert c.log_finalization_info_rate_s == 60
    assert c.redactor is None
    assert c.session_dir is None


def test_env_override_for_sample(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "all")
    c = load_config_from_env()
    assert c.default_sample == "all"


def test_env_override_numeric_sample(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "0.05")
    c = load_config_from_env()
    assert c.default_sample == pytest.approx(0.05)


def test_env_override_off(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "off")
    c = load_config_from_env()
    assert c.default_sample == "off"


def test_env_log_finalization_zero_disables(monkeypatch):
    monkeypatch.setenv("AUTOPSY_LOG_FINALIZATION", "0")
    c = load_config_from_env()
    assert c.log_finalization is False


def test_env_session_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    c = load_config_from_env()
    assert c.session_dir == str(tmp_path)


def test_invalid_sample_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "garbage")
    c = load_config_from_env()
    assert c.default_sample == "errors"


def test_removed_fields_are_gone():
    c = LensConfig()
    for removed in ("gmi_api_key", "google_ai_api_key", "port", "auto_diagnose", "model"):
        assert not hasattr(c, removed), f"{removed} must not be on the new LensConfig"
