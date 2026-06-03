"""Detector sensitivity profiles apply to LensConfig."""
from __future__ import annotations

from autopsy.core.config import LensConfig, load_config_from_env
from autopsy.detectors.profiles import BALANCED, LENIENT, STRICT, apply_profile_to_lens_config


def test_strict_profile_enables_promote_on_warn():
    c = LensConfig()
    apply_profile_to_lens_config(c, STRICT)
    assert c.promote_on_warn is True
    assert c.max_capture_buffer_events == 256


def test_lenient_profile_disables_noisy_detectors():
    c = LensConfig()
    apply_profile_to_lens_config(c, LENIENT)
    assert "unhandled_exception" not in c.enabled_detectors
    assert c.max_capture_buffer_events == 2048


def test_balanced_includes_warn_tier():
    c = LensConfig()
    apply_profile_to_lens_config(c, BALANCED)
    assert "high_latency" in c.enabled_detectors


def test_env_detector_profile(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DETECTOR_PROFILE", "strict")
    c = load_config_from_env()
    assert c.promote_on_warn is True
