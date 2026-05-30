"""Tests for the detector registry."""
from __future__ import annotations

from autopsy.core.config import LensConfig
from autopsy.detectors.registry import (
    builtin_detectors,
    get,
    register,
    resolve_enabled,
)


class _FakeDetector:
    name = "fake"

    def evaluate(self, events, *, outcome: str):
        return None


def test_builtin_detectors_has_three():
    b = builtin_detectors()
    assert set(b) == {"empty_response", "tool_loop", "missing_output"}


def test_register_and_get():
    d = _FakeDetector()
    register(d)
    assert get("fake") is d


def test_resolve_enabled_uses_config():
    cfg = LensConfig(enabled_detectors=["tool_loop"])
    names = [d.name for d in resolve_enabled(cfg)]
    assert names == ["tool_loop"]


def test_resolve_enabled_empty_when_off():
    cfg = LensConfig(enabled_detectors=[])
    assert resolve_enabled(cfg) == []
