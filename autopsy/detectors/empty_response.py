from __future__ import annotations

from autopsy.core.events import (
    AgentEndEvent,
    BaseEvent,
    DetectorVerdictEvent,
    EventKind,
    LLMResponseEvent,
)


def _fail(reason: str, *, score: float = 1.0) -> DetectorVerdictEvent:
    return DetectorVerdictEvent(
        event_id="",
        parent_id=None,
        session_id="",
        trace_id="",
        timestamp_ns=0,
        kind=EventKind.DETECTOR_VERDICT,
        detector_name="empty_response",
        verdict="fail",
        score=score,
        reason=reason,
    )


class EmptyResponseDetector:
    name = "empty_response"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        last_llm_idx: int | None = None
        for i, ev in enumerate(events):
            if isinstance(ev, LLMResponseEvent):
                last_llm_idx = i

        if last_llm_idx is None:
            return None

        last_llm = events[last_llm_idx]
        assert isinstance(last_llm, LLMResponseEvent)
        if last_llm.content.strip():
            return None

        for ev in events[last_llm_idx + 1:]:
            if isinstance(ev, AgentEndEvent) and ev.output_preview.strip():
                return None

        return _fail("LLM returned empty content")
