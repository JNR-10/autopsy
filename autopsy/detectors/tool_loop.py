from __future__ import annotations

from autopsy.core.config import LensConfig
from autopsy.core.events import (
    BaseEvent,
    DetectorVerdictEvent,
    EventKind,
    ToolCallStartEvent,
)


def _fail(reason: str) -> DetectorVerdictEvent:
    return DetectorVerdictEvent(
        event_id="",
        parent_id=None,
        session_id="",
        trace_id="",
        timestamp_ns=0,
        kind=EventKind.DETECTOR_VERDICT,
        detector_name="tool_loop",
        verdict="fail",
        reason=reason,
    )


class ToolLoopDetector:
    name = "tool_loop"

    def __init__(self, config: LensConfig | None = None) -> None:
        self._config = config or LensConfig()

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        tool_starts = [ev for ev in events if isinstance(ev, ToolCallStartEvent)]

        max_calls = self._config.max_tool_calls
        if len(tool_starts) >= max_calls:
            return _fail(f"total tool calls ({len(tool_starts)}) reached limit ({max_calls})")

        threshold = self._config.tool_loop_threshold
        consecutive = 0
        prev_name: str | None = None
        for ev in tool_starts:
            if ev.tool_name == prev_name:
                consecutive += 1
            else:
                consecutive = 1
                prev_name = ev.tool_name
            if consecutive >= threshold:
                return _fail(f"tool '{ev.tool_name}' started {consecutive} times consecutively")

        return None
