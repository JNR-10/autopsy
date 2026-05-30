"""Failure detectors — pluggable semantic failure heuristics."""
from __future__ import annotations

from .registry import builtin_detectors, get, register, resolve_enabled
from .runner import run_detectors

__all__ = [
    "register", "get", "builtin_detectors", "resolve_enabled", "run_detectors",
]
