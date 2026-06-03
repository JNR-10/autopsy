from __future__ import annotations

from autopsy.core.events import (
    BaseEvent,
    DetectorVerdictEvent,
    LLMResponseEvent,
    ToolCallStartEvent,
)
from autopsy.detectors._verdict import fail


class LLMToolWithoutExecutionDetector:
    name = "llm_tool_without_execution"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        for i, ev in enumerate(events):
            if not isinstance(ev, LLMResponseEvent) or not ev.tool_calls:
                continue
            if not any(isinstance(e, ToolCallStartEvent) for e in events[i + 1:]):
                return fail(
                    self.name,
                    f"LLM returned {len(ev.tool_calls)} tool call(s) but none were executed",
                )
        return None
