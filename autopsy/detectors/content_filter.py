from __future__ import annotations

from autopsy.core.events import BaseEvent, DetectorVerdictEvent, LLMResponseEvent
from autopsy.detectors._verdict import fail

_FILTER_REASONS = frozenset({
    "content_filter",
    "content_filtering",
    "safety",
    "blocked",
})


class ContentFilterDetector:
    name = "content_filter"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        for ev in events:
            if not isinstance(ev, LLMResponseEvent):
                continue
            reason = (ev.finish_reason or "").strip().lower()
            if reason in _FILTER_REASONS:
                return fail(self.name, f"LLM blocked by provider (finish_reason={ev.finish_reason!r})")
        return None
