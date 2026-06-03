from __future__ import annotations

import json
from collections import Counter

from autopsy.core.config import LensConfig
from autopsy.core.events import BaseEvent, DetectorVerdictEvent, ToolCallStartEvent
from autopsy.detectors._verdict import fail


class DuplicateToolArgsDetector:
    name = "duplicate_tool_args"

    def __init__(self, config: LensConfig | None = None) -> None:
        self._threshold = (config or LensConfig()).duplicate_tool_threshold

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        counts: Counter[str] = Counter()
        for ev in events:
            if not isinstance(ev, ToolCallStartEvent):
                continue
            key = f"{ev.tool_name}:{json.dumps(ev.tool_args, sort_keys=True, default=str)}"
            counts[key] += 1
            if counts[key] >= self._threshold:
                return fail(
                    self.name,
                    f"tool '{ev.tool_name}' invoked {counts[key]} times with identical arguments",
                )
        return None
