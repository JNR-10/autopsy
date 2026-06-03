from __future__ import annotations

from autopsy.core.events import (
    BaseEvent,
    DetectorVerdictEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from autopsy.detectors._verdict import fail


class OrphanToolCallDetector:
    name = "orphan_tool_call"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        starts = sum(1 for ev in events if isinstance(ev, ToolCallStartEvent))
        ends = sum(1 for ev in events if isinstance(ev, ToolCallEndEvent))
        if starts > ends:
            return fail(self.name, f"tool starts ({starts}) exceed tool ends ({ends})")
        return None
