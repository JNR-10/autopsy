"""Tests for unified AutopsyConfig."""
from __future__ import annotations

from autopsy.config import AutopsyConfig, load_config


def test_load_config_unifies_capture_and_diagnose(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "all")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AUTOPSY_PORT", "9000")
    monkeypatch.setenv("AUTOPSY_DEMO", "1")
    cfg = load_config()
    assert cfg.capture.default_sample == "all"
    assert cfg.diagnose.openai_api_key == "sk-test"
    assert cfg.server_port == 9000
    assert cfg.demo_enabled is True


def test_autopsy_config_defaults():
    cfg = AutopsyConfig()
    assert cfg.capture.default_sample == "errors"
    assert cfg.diagnose.default_model == "auto"
    assert cfg.demo_enabled is False
