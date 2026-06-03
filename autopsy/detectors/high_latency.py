from __future__ import annotations

from autopsy.core.config import LensConfig
from autopsy.core.events import (
    AgentEndEvent,
    BaseEvent,
    DetectorVerdictEvent,
    LLMResponseEvent,
)
from autopsy.detectors._verdict import warn


class HighLatencyDetector:
    name = "high_latency"

    def __init__(self, config: LensConfig | None = None) -> None:
        self._threshold_ms = (config or LensConfig()).latency_threshold_ms

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        worst_ms = 0.0
        label = ""
        for ev in events:
            if isinstance(ev, LLMResponseEvent) and ev.latency_ms > worst_ms:
                worst_ms = ev.latency_ms
                label = f"LLM call took {worst_ms:.0f}ms"
            if isinstance(ev, AgentEndEvent) and ev.duration_ms > worst_ms:
                worst_ms = ev.duration_ms
                label = f"agent span took {worst_ms:.0f}ms"
        if worst_ms >= self._threshold_ms:
            return warn(self.name, f"{label} (threshold {self._threshold_ms}ms)")
        return None
