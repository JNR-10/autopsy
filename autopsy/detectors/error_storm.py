from __future__ import annotations

from autopsy.core.config import LensConfig
from autopsy.core.events import BaseEvent, DetectorVerdictEvent, ErrorEvent
from autopsy.detectors._verdict import warn


class ErrorStormDetector:
    name = "error_storm"

    def __init__(self, config: LensConfig | None = None) -> None:
        self._threshold = (config or LensConfig()).error_storm_threshold

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        n = sum(1 for ev in events if isinstance(ev, ErrorEvent))
        if n >= self._threshold:
            return warn(self.name, f"{n} error events recorded in session")
        return None
