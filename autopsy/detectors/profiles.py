"""Detector sensitivity profiles — tune thresholds and defaults per workload."""
from __future__ import annotations

from dataclasses import dataclass

from autopsy.detectors.defaults import DEFAULT_ENABLED_DETECTORS, OPTIONAL_DETECTORS


@dataclass(frozen=True, slots=True)
class DetectorProfile:
    name: str
    enabled_detectors: tuple[str, ...]
    max_capture_buffer_events: int
    max_capture_buffer_bytes: int
    tool_loop_threshold: int
    max_tool_calls: int
    latency_threshold_ms: int
    duplicate_tool_threshold: int
    error_storm_threshold: int
    promote_on_warn: bool


STRICT = DetectorProfile(
    name="strict",
    enabled_detectors=DEFAULT_ENABLED_DETECTORS,
    max_capture_buffer_events=256,
    max_capture_buffer_bytes=2_097_152,
    tool_loop_threshold=4,
    max_tool_calls=40,
    latency_threshold_ms=60_000,
    duplicate_tool_threshold=4,
    error_storm_threshold=2,
    promote_on_warn=True,
)

BALANCED = DetectorProfile(
    name="balanced",
    enabled_detectors=DEFAULT_ENABLED_DETECTORS + OPTIONAL_DETECTORS,
    max_capture_buffer_events=1024,
    max_capture_buffer_bytes=8_388_608,
    tool_loop_threshold=5,
    max_tool_calls=80,
    latency_threshold_ms=30_000,
    duplicate_tool_threshold=3,
    error_storm_threshold=3,
    promote_on_warn=False,
)

LENIENT = DetectorProfile(
    name="lenient",
    enabled_detectors=tuple(
        d for d in DEFAULT_ENABLED_DETECTORS
        if d not in ("unhandled_exception", "duplicate_tool_args", "token_budget_empty")
    ),
    max_capture_buffer_events=2048,
    max_capture_buffer_bytes=16_777_216,
    tool_loop_threshold=8,
    max_tool_calls=120,
    latency_threshold_ms=120_000,
    duplicate_tool_threshold=5,
    error_storm_threshold=5,
    promote_on_warn=False,
)

_PROFILES: dict[str, DetectorProfile] = {
    "strict": STRICT,
    "balanced": BALANCED,
    "lenient": LENIENT,
}


def available_profiles() -> list[str]:
    return list(_PROFILES.keys())


def get_profile(name: str) -> DetectorProfile | None:
    return _PROFILES.get(name.strip().lower())


def apply_profile_to_lens_config(config: object, profile: DetectorProfile) -> None:
    """Mutate a LensConfig in place from a profile."""
    config.enabled_detectors = list(profile.enabled_detectors)
    config.max_capture_buffer_events = profile.max_capture_buffer_events
    config.max_capture_buffer_bytes = profile.max_capture_buffer_bytes
    config.tool_loop_threshold = profile.tool_loop_threshold
    config.max_tool_calls = profile.max_tool_calls
    config.latency_threshold_ms = profile.latency_threshold_ms
    config.duplicate_tool_threshold = profile.duplicate_tool_threshold
    config.error_storm_threshold = profile.error_storm_threshold
    config.promote_on_warn = profile.promote_on_warn
