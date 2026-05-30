"""Shared LLM response parsing for diagnose providers."""
from __future__ import annotations

import json
import re
from typing import Any

from .types import DiagnosisResult


def extract_json(text: str) -> dict[str, Any] | None:
    """Try several strategies to extract a JSON object from an LLM response."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return None


def diagnosis_from_parsed(
    parsed: dict[str, Any],
    heuristic: DiagnosisResult,
    *,
    raw: str = "",
) -> DiagnosisResult:
    """Map parsed LLM JSON fields onto DiagnosisResult."""
    return DiagnosisResult(
        root_cause=str(parsed.get("root_cause", heuristic.root_cause))[:1500],
        affected_node_id=str(parsed.get("affected_node_id", heuristic.affected_node_id)),
        affected_node_name=str(parsed.get(
            "affected_node_name", heuristic.affected_node_name)),
        error_category=str(parsed.get("error_category", heuristic.error_category)),
        fix_suggestion=str(parsed.get("fix_suggestion", heuristic.fix_suggestion))[:2000],
        fix_code_snippet=str(parsed.get("fix_code_snippet", ""))[:3000],
        confidence=float(parsed.get("confidence", 0.7) or 0.7),
        latency_insight=str(parsed.get("latency_insight", ""))[:1000],
        estimated_latency_savings_ms=float(
            parsed.get("estimated_latency_savings_ms", 0) or 0),
        model_swap_suggestion=str(parsed.get("model_swap_suggestion", ""))[:500],
        raw_response=(raw or "")[:4000],
    )
