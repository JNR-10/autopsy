from __future__ import annotations

from autopsy.core.events import BaseEvent, DetectorVerdictEvent, LLMResponseEvent
from autopsy.detectors._verdict import fail


class TokenBudgetEmptyDetector:
    name = "token_budget_empty"
    min_completion_tokens: int = 32

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        for ev in events:
            if not isinstance(ev, LLMResponseEvent):
                continue
            if ev.completion_tokens < self.min_completion_tokens:
                continue
            if ev.content.strip() or ev.tool_calls:
                continue
            return fail(
                self.name,
                f"LLM used {ev.completion_tokens} completion tokens but returned empty content",
            )
        return None
