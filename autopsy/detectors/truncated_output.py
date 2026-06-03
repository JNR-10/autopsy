from __future__ import annotations

from autopsy.core.events import BaseEvent, DetectorVerdictEvent, LLMResponseEvent
from autopsy.detectors._verdict import fail

_TRUNCATED_REASONS = frozenset({
    "length",
    "max_tokens",
    "model_length",
    "incomplete",
})


class TruncatedOutputDetector:
    name = "truncated_output"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        for ev in events:
            if not isinstance(ev, LLMResponseEvent):
                continue
            reason = (ev.finish_reason or "").strip().lower()
            if reason in _TRUNCATED_REASONS:
                return fail(
                    self.name,
                    f"LLM output truncated (finish_reason={ev.finish_reason!r})",
                )
        return None
