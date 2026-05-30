from __future__ import annotations

from autopsy.core.events import (
    AgentEndEvent,
    BaseEvent,
    DetectorVerdictEvent,
    EventKind,
    LLMRequestEvent,
    LLMResponseEvent,
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
        detector_name="missing_output",
        verdict="fail",
        reason=reason,
    )


class MissingOutputDetector:
    name = "missing_output"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        if outcome != "ok":
            return None

        has_activity = any(
            isinstance(ev, (LLMRequestEvent, ToolCallStartEvent)) for ev in events
        )
        if not has_activity:
            return None

        for ev in events:
            if isinstance(ev, LLMResponseEvent) and ev.content.strip():
                return None
            if isinstance(ev, AgentEndEvent) and ev.output_preview.strip():
                return None

        return _fail("session completed without agent output")
