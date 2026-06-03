from __future__ import annotations

from autopsy.core.events import BaseEvent, DetectorVerdictEvent, ErrorEvent
from autopsy.detectors._verdict import fail


class UnhandledExceptionDetector:
    name = "unhandled_exception"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        if outcome != "ok":
            return None
        errors = [ev for ev in events if isinstance(ev, ErrorEvent)]
        if not errors:
            return None
        first = errors[0]
        return fail(
            self.name,
            f"session outcome ok but {len(errors)} error event(s); first: {first.error_type}",
        )
