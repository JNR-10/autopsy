from __future__ import annotations

from typing import Protocol, runtime_checkable

from autopsy.core.config import LensConfig
from autopsy.core.events import BaseEvent, DetectorVerdictEvent
from autopsy.detectors.defaults import DEFAULT_ENABLED_DETECTORS

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
    from .content_filter import ContentFilterDetector
    from .duplicate_tool_args import DuplicateToolArgsDetector
    from .empty_response import EmptyResponseDetector
    from .error_storm import ErrorStormDetector
    from .high_latency import HighLatencyDetector
    from .llm_tool_without_execution import LLMToolWithoutExecutionDetector
    from .missing_output import MissingOutputDetector
    from .orphan_llm import OrphanLLMDetector
    from .orphan_tool_call import OrphanToolCallDetector
    from .token_budget_empty import TokenBudgetEmptyDetector
    from .tool_failure import ToolFailureDetector
    from .tool_loop import ToolLoopDetector
    from .truncated_output import TruncatedOutputDetector
    from .unhandled_exception import UnhandledExceptionDetector

    return {
        "empty_response": EmptyResponseDetector(),
        "tool_loop": ToolLoopDetector(),
        "missing_output": MissingOutputDetector(),
        "tool_failure": ToolFailureDetector(),
        "truncated_output": TruncatedOutputDetector(),
        "orphan_tool_call": OrphanToolCallDetector(),
        "orphan_llm": OrphanLLMDetector(),
        "llm_tool_without_execution": LLMToolWithoutExecutionDetector(),
        "unhandled_exception": UnhandledExceptionDetector(),
        "token_budget_empty": TokenBudgetEmptyDetector(),
        "content_filter": ContentFilterDetector(),
        "duplicate_tool_args": DuplicateToolArgsDetector(),
        "high_latency": HighLatencyDetector(),
        "error_storm": ErrorStormDetector(),
    }


def builtin_detectors() -> dict[str, Detector]:
    return dict(_builtin_instances())


def resolve_enabled(config: LensConfig) -> list[Detector]:
    from .duplicate_tool_args import DuplicateToolArgsDetector
    from .error_storm import ErrorStormDetector
    from .high_latency import HighLatencyDetector
    from .tool_loop import ToolLoopDetector

    factories: dict[str, type] = {
        "tool_loop": ToolLoopDetector,
        "duplicate_tool_args": DuplicateToolArgsDetector,
        "high_latency": HighLatencyDetector,
        "error_storm": ErrorStormDetector,
    }

    out: list[Detector] = []
    for name in config.enabled_detectors:
        if name in factories:
            out.append(factories[name](config=config))
            continue
        d = get(name)
        if d is not None:
            out.append(d)
    return out


def default_enabled_detector_names() -> list[str]:
    return list(DEFAULT_ENABLED_DETECTORS)
