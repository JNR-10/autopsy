"""Ready-made LensConfig presets for production deployments."""
from __future__ import annotations

from typing import Any

from autopsy.detectors.defaults import DEFAULT_ENABLED_DETECTORS, OPTIONAL_DETECTORS
from autopsy.detectors.profiles import STRICT, apply_profile_to_lens_config


def apply_production_alerting(config: Any) -> None:
    """High-stakes silent-failure alerting: strict thresholds + warn persistence.

    Equivalent to AUTOPSY_PRODUCTION_ALERTING=1 / AUTOPSY_DETECTOR_PROFILE=strict
    with explicit detector list including warn-tier checks.
    """
    apply_profile_to_lens_config(config, STRICT)
    config.promote_on_warn = True
    config.enabled_detectors = list(DEFAULT_ENABLED_DETECTORS) + list(OPTIONAL_DETECTORS)
    config.max_detector_ring_events = max(config.max_detector_ring_events, 8192)
    # Full trace (disk tail merge) is opt-in: AUTOPSY_DETECTOR_FULL_TRACE=1
