from __future__ import annotations

from autopsy.core.events import (
    BaseEvent,
    DetectorVerdictEvent,
    LLMRequestEvent,
    LLMResponseEvent,
)
from autopsy.detectors._verdict import fail


class OrphanLLMDetector:
    name = "orphan_llm"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        requests = sum(1 for ev in events if isinstance(ev, LLMRequestEvent))
        responses = sum(1 for ev in events if isinstance(ev, LLMResponseEvent))
        if requests > responses:
            return fail(self.name, f"LLM requests ({requests}) exceed responses ({responses})")
        return None
