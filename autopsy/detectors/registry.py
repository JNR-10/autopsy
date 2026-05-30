from __future__ import annotations

from typing import Protocol, runtime_checkable

from autopsy.core.config import LensConfig
from autopsy.core.events import BaseEvent, DetectorVerdictEvent

_custom: dict[str, "Detector"] = {}


@runtime_checkable
class Detector(Protocol):
    name: str

    def evaluate(
        self, events: list[BaseEvent], *, outcome: str,
    ) -> DetectorVerdictEvent | None: ...


def register(detector: Detector) -> None:
    _custom[detector.name] = detector


def get(name: str) -> Detector | None:
    if name in _custom:
        return _custom[name]
    return _builtin_instances().get(name)


def _builtin_instances() -> dict[str, Detector]:
    from .empty_response import EmptyResponseDetector
    from .tool_loop import ToolLoopDetector
    from .missing_output import MissingOutputDetector
    return {
        "empty_response": EmptyResponseDetector(),
        "tool_loop": ToolLoopDetector(),
        "missing_output": MissingOutputDetector(),
    }


def builtin_detectors() -> dict[str, Detector]:
    return dict(_builtin_instances())


def resolve_enabled(config: LensConfig) -> list[Detector]:
    from .tool_loop import ToolLoopDetector

    out: list[Detector] = []
    for name in config.enabled_detectors:
        if name == "tool_loop":
            out.append(ToolLoopDetector(config=config))
            continue
        d = get(name)
        if d is not None:
            out.append(d)
    return out
