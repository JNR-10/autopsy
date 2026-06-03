from __future__ import annotations

from autopsy.core.events import BaseEvent, DetectorVerdictEvent, ToolCallEndEvent
from autopsy.detectors._verdict import fail


class ToolFailureDetector:
    name = "tool_failure"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        for ev in events:
            if isinstance(ev, ToolCallEndEvent) and ev.error:
                return fail(self.name, f"tool '{ev.tool_name}' failed: {ev.error[:200]}")
        return None
