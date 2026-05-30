"""Local heuristic diagnosis — no LLM required."""
from __future__ import annotations

from typing import Any

from .types import DiagnosisResult


def diagnose_heuristic(
    bundle: dict[str, Any],
    target_node_id: str | None = None,
) -> DiagnosisResult:
    """Produce a useful diagnosis from the bundle alone."""
    events = bundle.get("events") or []
    node_index = bundle.get("node_index") or {}
    if not target_node_id:
        for ev in events:
            if ev.get("event_type") == "node_error":
                target_node_id = ev.get("node_id")
                break
    nidx = node_index.get(target_node_id or "", {})
    start = nidx.get("start_event") or {}
    err = nidx.get("error_event") or {}
    err_msg = (err.get("error_message") or "").lower()
    err_type = err.get("error_type", "")
    node_name = start.get("node_name", "unknown")

    if "json" in err_msg or err_type == "JSONDecodeError" or "decode" in err_msg:
        category = "bad_json"
        cause = (
            f"The {node_name} node received malformed JSON, likely because the upstream "
            f"context exceeded the model's effective limit and the model truncated its output."
        )
        fix = (
            "Chunk the input before sending it to the summarizer. Split the search results "
            "into smaller pieces (~1500 chars each), summarize each chunk separately, then "
            "combine the chunk summaries."
        )
        snippet = (
            "async def summarizer_agent(context: str) -> dict:\n"
            "    CHUNK_SIZE = 1500\n"
            "    chunks = [context[i:i + CHUNK_SIZE] "
            "for i in range(0, len(context), CHUNK_SIZE)]\n"
            "    summaries = [await summarize_chunk(c) for c in chunks]\n"
            "    return {'summary': ' '.join(summaries), 'key_points': []}"
        )
    elif "context" in err_msg or "overflow" in err_msg or "too long" in err_msg:
        category = "context_overflow"
        cause = (
            f"The {node_name} node was given a context that exceeds the model's safe input window."
        )
        fix = (
            "Add a truncation step or summarization pre-pass before this node. "
            "Cap inputs to 8k chars and chunk anything larger."
        )
        snippet = (
            "MAX_CONTEXT = 8000\n"
            "context = context[:MAX_CONTEXT]"
        )
    elif "timeout" in err_msg or err_type in ("TimeoutError", "asyncio.TimeoutError"):
        category = "timeout"
        cause = f"The {node_name} node timed out."
        fix = "Increase the request timeout or break work into smaller calls."
        snippet = ""
    elif err_type:
        category = "tool_failure"
        cause = f"The {node_name} node raised {err_type}: {err.get('error_message', '')[:200]}"
        fix = "Add input validation and a retry-with-backoff wrapper at this node."
        snippet = ""
    else:
        category = "other"
        cause = "No obvious error detected; the trace may have a quality issue rather than a failure."
        fix = "Run replay with a different model to compare outputs."
        snippet = ""

    return DiagnosisResult(
        root_cause=cause,
        affected_node_id=target_node_id or "",
        affected_node_name=node_name,
        error_category=category,
        fix_suggestion=fix,
        fix_code_snippet=snippet,
        confidence=0.6,
        latency_insight="",
        estimated_latency_savings_ms=0.0,
        model_swap_suggestion="",
        raw_response="(local heuristic - LLM unavailable)",
    )


class HeuristicProvider:
    """Built-in provider that never calls an external LLM."""

    @property
    def name(self) -> str:
        return "heuristic"

    async def diagnose(
        self,
        bundle: dict[str, Any],
        target_node_id: str | None = None,
    ) -> DiagnosisResult:
        return diagnose_heuristic(bundle, target_node_id)
