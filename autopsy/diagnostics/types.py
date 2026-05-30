"""Diagnostics result types."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiagnosisResult:
    """Canonical diagnosis returned by GMIAgent/GeminiAgent."""

    root_cause: str = ""
    affected_node_id: str = ""
    affected_node_name: str = ""
    error_category: str = "other"
    fix_suggestion: str = ""
    fix_code_snippet: str = ""
    confidence: float = 0.0
    latency_insight: str = ""
    estimated_latency_savings_ms: float = 0.0
    model_swap_suggestion: str = ""
    raw_response: str = ""
