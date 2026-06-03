"""Detector defaults — no imports from registry or core.config (avoids cycles)."""

DEFAULT_ENABLED_DETECTORS: tuple[str, ...] = (
    "empty_response",
    "tool_loop",
    "missing_output",
    "tool_failure",
    "truncated_output",
    "orphan_tool_call",
    "orphan_llm",
    "llm_tool_without_execution",
    "unhandled_exception",
    "token_budget_empty",
    "content_filter",
    "duplicate_tool_args",
)

OPTIONAL_DETECTORS: tuple[str, ...] = (
    "high_latency",
    "error_storm",
)
