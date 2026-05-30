from __future__ import annotations

import logging
import time

from autopsy.core.events import DetectorVerdictEvent
from autopsy.core.ulid import new_ulid
from autopsy.detectors.registry import Detector

logger = logging.getLogger("autopsy.detectors")


def run_detectors(
    *,
    events: list,
    outcome: str,
    session_id: str,
    trace_id: str,
    parent_id: str | None,
    detectors: list[Detector],
) -> list[DetectorVerdictEvent]:
    verdicts: list[DetectorVerdictEvent] = []
    for det in detectors:
        try:
            v = det.evaluate(events, outcome=outcome)
        except Exception:
            logger.warning("autopsy: detector %s raised", getattr(det, "name", det), exc_info=True)
            continue
        if v is None:
            continue
        if v.session_id != session_id:
            v = v.model_copy(update={"session_id": session_id, "trace_id": trace_id})
        if v.event_id in ("", None):
            v = v.model_copy(update={"event_id": new_ulid()})
        if v.timestamp_ns == 0:
            v = v.model_copy(update={"timestamp_ns": time.time_ns()})
        verdicts.append(v)
    return verdicts
