"""Production alerting preset and per-call overrides."""
from __future__ import annotations

from autopsy.core.config import LensConfig, load_config_from_env
from autopsy.detectors.overrides import DetectorCallOverrides, lens_config_for_detectors
from autopsy.detectors.presets import apply_production_alerting


def test_production_alerting_preset():
    c = LensConfig()
    apply_production_alerting(c)
    assert c.promote_on_warn is True
    assert "high_latency" in c.enabled_detectors
    assert c.detector_full_trace is False
    assert c.max_detector_ring_events >= 8192


def test_env_production_alerting(monkeypatch):
    monkeypatch.setenv("AUTOPSY_PRODUCTION_ALERTING", "1")
    c = load_config_from_env(LensConfig())
    assert c.promote_on_warn is True


def test_per_call_strict_profile_overrides_threshold():
    base = LensConfig(tool_loop_threshold=10)
    cfg = lens_config_for_detectors(
        base,
        overrides=DetectorCallOverrides(
            detector_profile="strict",
            tool_loop_threshold=2,
        ),
    )
    assert cfg.tool_loop_threshold == 2
    assert cfg.promote_on_warn is True
