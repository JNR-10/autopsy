"""Built-in detector catalog — names, defaults, and human-readable descriptions."""
from __future__ import annotations

from dataclasses import dataclass

from autopsy.detectors.defaults import DEFAULT_ENABLED_DETECTORS


def _default_enabled(name: str) -> bool:
    return name in DEFAULT_ENABLED_DETECTORS


@dataclass(frozen=True, slots=True)
class DetectorInfo:
    name: str
    description: str
    default_enabled: bool


def _entry(name: str, description: str) -> DetectorInfo:
    return DetectorInfo(name, description, _default_enabled(name))


_CATALOG: tuple[DetectorInfo, ...] = (
    _entry("empty_response", "Last LLM response has no text and no later agent output."),
    _entry("tool_loop", "Same tool invoked consecutively too many times or total tool cap hit."),
    _entry("missing_output", "Session succeeded but produced no LLM or agent output after work."),
    _entry("tool_failure", "One or more tool calls ended with an error string."),
    _entry("truncated_output", "LLM finish_reason indicates length/max_tokens truncation."),
    _entry("orphan_tool_call", "Unpaired tool starts without matching ends."),
    _entry("orphan_llm", "More LLM requests than responses (timeout or dropped stream)."),
    _entry(
        "llm_tool_without_execution",
        "Model returned tool_calls but no tool ran before the next LLM turn.",
    ),
    _entry("unhandled_exception", "Session outcome is ok but unhandled ErrorEvent(s) were recorded."),
    _entry(
        "token_budget_empty",
        "High completion token count with empty visible content (hidden failure).",
    ),
    _entry("content_filter", "Provider content-filter or safety block on LLM response."),
    _entry("duplicate_tool_args", "Same tool+arguments repeated many times (stuck retry)."),
    _entry("high_latency", "LLM or agent span exceeded latency threshold (warn)."),
    _entry("error_storm", "Many ErrorEvents in one session (warn)."),
)


def detector_catalog() -> list[DetectorInfo]:
    return list(_CATALOG)


def all_builtin_names() -> list[str]:
    return [d.name for d in _CATALOG]
