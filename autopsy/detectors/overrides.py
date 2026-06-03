"""Per-call detector overrides (decorator / Session.begin)."""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any

from autopsy.detectors.profiles import apply_profile_to_lens_config, get_profile


@dataclass
class DetectorCallOverrides:
    detector_profile: str | None = None
    promote_on_warn: bool | None = None
    tool_loop_threshold: int | None = None
    max_tool_calls: int | None = None
    latency_threshold_ms: int | None = None
    duplicate_tool_threshold: int | None = None
    error_storm_threshold: int | None = None
    max_capture_buffer_events: int | None = None
    max_capture_buffer_bytes: int | None = None

    def apply_to(self, config: Any) -> Any:
        """Return a LensConfig copy with profile + field overrides applied."""
        cfg = replace(config)
        if self.detector_profile:
            prof = get_profile(self.detector_profile)
            if prof is not None:
                apply_profile_to_lens_config(cfg, prof)
        for f in fields(self):
            if f.name == "detector_profile":
                continue
            val = getattr(self, f.name)
            if val is not None and hasattr(cfg, f.name):
                cfg = replace(cfg, **{f.name: val})
        return cfg


def lens_config_for_detectors(base: Any, *, overrides: DetectorCallOverrides | None) -> Any:
    if overrides is None:
        return replace(base)
    return overrides.apply_to(base)
