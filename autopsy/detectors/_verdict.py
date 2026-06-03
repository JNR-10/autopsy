"""Shared helpers for building detector verdict events."""
from __future__ import annotations

from autopsy.core.events import DetectorVerdictEvent, EventKind


def verdict(
    detector_name: str,
    reason: str,
    *,
    verdict: str = "fail",
    score: float = 1.0,
) -> DetectorVerdictEvent:
    return DetectorVerdictEvent(
        event_id="",
        parent_id=None,
        session_id="",
        trace_id="",
        timestamp_ns=0,
        kind=EventKind.DETECTOR_VERDICT,
        detector_name=detector_name,
        verdict=verdict,  # type: ignore[arg-type]
        score=score,
        reason=reason,
    )


def fail(detector_name: str, reason: str, *, score: float = 1.0) -> DetectorVerdictEvent:
    return verdict(detector_name, reason, verdict="fail", score=score)


def warn(detector_name: str, reason: str, *, score: float = 0.5) -> DetectorVerdictEvent:
    return verdict(detector_name, reason, verdict="warn", score=score)
