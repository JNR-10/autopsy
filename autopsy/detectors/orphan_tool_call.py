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
        pending = 0
        for ev in events:
            if isinstance(ev, ToolCallStartEvent):
                pending += 1
            elif isinstance(ev, ToolCallEndEvent):
                if pending > 0:
                    pending -= 1
        if pending > 0:
            return fail(self.name, f"{pending} tool call(s) started without matching end")
        return None
