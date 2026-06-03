from __future__ import annotations

from autopsy.core.events import (
    AgentEndEvent,
    BaseEvent,
    DetectorVerdictEvent,
    LLMRequestEvent,
    LLMResponseEvent,
    ToolCallStartEvent,
)
from autopsy.detectors._verdict import fail


def _tool_executed_before_next_turn(events: list[BaseEvent], start_idx: int) -> bool:
    for ev in events[start_idx + 1:]:
        if isinstance(ev, ToolCallStartEvent):
            return True
        if isinstance(ev, (LLMRequestEvent, AgentEndEvent)):
            return False
    return False


class LLMToolWithoutExecutionDetector:
    name = "llm_tool_without_execution"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        for i, ev in enumerate(events):
            if not isinstance(ev, LLMResponseEvent) or not ev.tool_calls:
                continue
            if not _tool_executed_before_next_turn(events, i):
                return fail(
                    self.name,
                    f"LLM returned {len(ev.tool_calls)} tool call(s) but none were executed",
                )
        return None
