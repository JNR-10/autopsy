"""Failure detectors — pluggable semantic failure heuristics."""
from __future__ import annotations

from autopsy.detectors.defaults import DEFAULT_ENABLED_DETECTORS, OPTIONAL_DETECTORS

__all__ = [
    "DEFAULT_ENABLED_DETECTORS",
    "OPTIONAL_DETECTORS",
    "register",
    "get",
    "builtin_detectors",
    "default_enabled_detector_names",
    "resolve_enabled",
    "run_detectors",
    "detector_catalog",
]


def __getattr__(name: str):
    if name == "detector_catalog":
        from autopsy.detectors.catalog import detector_catalog

        return detector_catalog
    if name in (
        "register",
        "get",
        "builtin_detectors",
        "default_enabled_detector_names",
        "resolve_enabled",
    ):
        from autopsy.detectors import registry as reg

        return getattr(reg, name)
    if name == "run_detectors":
        from autopsy.detectors.runner import run_detectors

        return run_detectors
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
