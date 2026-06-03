"""Build legacy TraceBundle indexes from legacy-shaped event lists."""
from __future__ import annotations

from typing import Any


def build_legacy_node_index(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Mirror dashboard `buildLiveBundle()` — node_index for v1-native reads."""
    node_index: dict[str, dict[str, Any]] = {}
    for e in events:
        t = e.get("event_type")
        nid = e.get("node_id")
        if not nid and t not in ("session_start", "session_end"):
            continue
        if t == "node_start":
            node_index.setdefault(nid, {})["start_event"] = e
        elif t == "node_end":
            node_index.setdefault(nid, {})["end_event"] = e
        elif t == "node_error":
            node_index.setdefault(nid, {})["error_event"] = e
        elif t in ("llm_request", "llm_response"):
            node_index.setdefault(nid, {}).setdefault("llm_events", []).append(e)
        elif t in ("tool_call", "tool_result"):
            node_index.setdefault(nid, {}).setdefault("tool_events", []).append(e)
    return node_index


def build_legacy_dag_edges(events: list[dict[str, Any]]) -> list[list[str]]:
    edges: list[list[str]] = []
    for e in events:
        if e.get("event_type") != "node_start":
            continue
        nid = e.get("node_id")
        parent = e.get("parent_node_id")
        if nid and parent:
            edges.append([parent, nid])
    return edges


def legacy_input_query(events: list[dict[str, Any]]) -> str:
    for e in events:
        if e.get("event_type") == "session_start":
            return str(e.get("input_query") or "")
        if e.get("event_type") == "node_start" and e.get("depth", 0) == 0:
            return str(e.get("input_data") or "")
    return ""
