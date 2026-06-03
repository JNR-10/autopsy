"""Built-in detector catalog — names, defaults, and human-readable descriptions."""
from __future__ import annotations

from dataclasses import dataclass

from autopsy.detectors.defaults import DEFAULT_ENABLED_DETECTORS, OPTIONAL_DETECTORS


@dataclass(frozen=True, slots=True)
class DetectorInfo:
    name: str
    description: str
    default_enabled: bool


_CATALOG: tuple[DetectorInfo, ...] = (
    DetectorInfo("empty_response", "Last LLM response has no text and no later agent output.", True),
    DetectorInfo("tool_loop", "Same tool invoked consecutively too many times or total tool cap hit.", True),
    DetectorInfo("missing_output", "Session succeeded but produced no LLM or agent output after work.", True),
    DetectorInfo("tool_failure", "One or more tool calls ended with an error string.", True),
    DetectorInfo("truncated_output", "LLM finish_reason indicates length/max_tokens truncation.", True),
    DetectorInfo("orphan_tool_call", "More tool starts than tool ends (dropped or crashed mid-tool).", True),
    DetectorInfo("orphan_llm", "More LLM requests than responses (timeout or dropped stream).", True),
    DetectorInfo(
        "llm_tool_without_execution",
        "Model returned tool_calls but no matching tool invocation followed.",
        True,
    ),
    DetectorInfo("unhandled_exception", "Session outcome is ok but ErrorEvent(s) were recorded.", True),
    DetectorInfo(
        "token_budget_empty",
        "High completion token count with empty visible content (hidden failure).",
        True,
    ),
    DetectorInfo("content_filter", "Provider content-filter or safety block on LLM response.", True),
    DetectorInfo("duplicate_tool_args", "Same tool+arguments repeated many times (stuck retry).", True),
    DetectorInfo("high_latency", "LLM or agent span exceeded latency threshold (warn).", False),
    DetectorInfo("error_storm", "Many ErrorEvents in one session (warn).", False),
)


def detector_catalog() -> list[DetectorInfo]:
    return list(_CATALOG)


def all_builtin_names() -> list[str]:
    return [d.name for d in _CATALOG]
