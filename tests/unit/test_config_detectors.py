"""Tests for detector-related LensConfig fields and env parsing."""
from __future__ import annotations

from autopsy.core.config import LensConfig, load_config_from_env


def test_default_enabled_detectors():
    c = LensConfig()
    assert c.enabled_detectors == ["empty_response", "tool_loop", "missing_output"]


def test_env_autopsy_detectors_off(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DETECTORS", "off")
    c = load_config_from_env()
    assert c.enabled_detectors == []


def test_env_autopsy_detectors_subset(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DETECTORS", "tool_loop,empty_response")
    c = load_config_from_env()
    assert c.enabled_detectors == ["tool_loop", "empty_response"]


def test_env_tool_loop_threshold(monkeypatch):
    monkeypatch.setenv("AUTOPSY_TOOL_LOOP_THRESHOLD", "3")
    c = load_config_from_env()
    assert c.tool_loop_threshold == 3


def test_env_promote_on_warn(monkeypatch):
    monkeypatch.setenv("AUTOPSY_PROMOTE_ON_WARN", "1")
    c = load_config_from_env()
    assert c.promote_on_warn is True
