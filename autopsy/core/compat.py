"""LegacyBundleReader — bilingual v0/v1 reader returning the old TraceBundle dict.

Why this exists: the dashboard, diagnostics, and replay engine consume the
old `TraceBundle` dict shape. Rewriting them is sub-project #5. Until then,
this module is the seam that lets us refactor the capture layer in isolation.

v0 = existing implicit format on disk: one JSON file per session containing
the full `TraceBundle` payload. Read it directly.

v1 = new format: per-session directory with `manifest.json` + `events.jsonl(.gz)`.
Read both and synthesize the legacy event-type vocabulary on the fly.

`read_v0_bundle` and `read_v1_bundle` are the per-format readers. The
unified `LegacyBundleReader` (added in 6.3) chooses between them.
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Any

from .errors import UnknownSchemaVersionError

logger = logging.getLogger("autopsy.compat")

_KIND_TO_LEGACY_TYPE = {
    "agent_start": "node_start",
    "agent_end": "node_end",
    "error": "node_error",
    "tool_call_start": "tool_call",
    "tool_call_end": "tool_result",
    "llm_request": "llm_request",
    "llm_response": "llm_response",
    "session_start": "session_start",
    "session_end": "session_end",
    "log": "node_start",
}


def read_v0_bundle(path: Path) -> dict[str, Any] | None:
    """Read a single legacy JSON-blob session file into a TraceBundle dict."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    bundle: dict[str, Any] = {
        "session_id": data.get("session_id", ""),
        "created_at": float(data.get("created_at", 0.0)),
        "agent_name": data.get("agent_name", ""),
        "input_query": data.get("input_query", ""),
        "agent_module_path": data.get("agent_module_path", ""),
        "agent_fn_name": data.get("agent_fn_name", ""),
        "events": list(data.get("events", []) or []),
        "dag_edges": list(data.get("dag_edges", []) or []),
        "node_index": dict(data.get("node_index", {}) or {}),
        "replay_checkpoints": dict(data.get("replay_checkpoints", {}) or {}),
        "summary": dict(data.get("summary", {}) or {}),
    }
    return bundle


def _v1_event_to_legacy(ev: dict[str, Any]) -> dict[str, Any] | None:
    kind = ev.get("kind")
    if kind == "detector_verdict":
        verdict = ev.get("verdict")
        if verdict == "pass":
            return None
        if verdict != "fail":
            return None
        legacy = dict(ev)
        legacy["event_type"] = "node_error"
        legacy["timestamp"] = ev.get("timestamp_ns", 0) / 1e9
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["error_type"] = f"detector:{ev.get('detector_name', '')}"
        legacy["error_message"] = ev.get("reason", "")
        legacy["duration_ms"] = 0
        return legacy
    legacy = dict(ev)
    legacy["event_type"] = _KIND_TO_LEGACY_TYPE.get(kind, kind)
    legacy["timestamp"] = ev.get("timestamp_ns", 0) / 1e9
    if kind == "agent_start":
        legacy["node_id"] = ev.get("event_id")
        legacy["node_type"] = ev.get("role", "agent")
        legacy["node_name"] = ev.get("agent_name", "")
        legacy["parent_node_id"] = ev.get("parent_id")
        legacy["depth"] = 0
        legacy["input_data"] = ev.get("input_preview", "")
    elif kind == "agent_end":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["duration_ms"] = ev.get("duration_ms", 0)
        legacy["output_data"] = ev.get("output_preview", "")
        legacy["output_hash"] = ev.get("output_hash", "")
    elif kind == "error":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["error_type"] = ev.get("error_type", "")
        legacy["error_message"] = ev.get("error_message", "")
        legacy["traceback"] = ev.get("traceback", "")
        legacy["duration_ms"] = 0
    elif kind == "tool_call_start":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["tool_name"] = ev.get("tool_name", "")
        legacy["tool_args"] = ev.get("tool_args", {})
    elif kind == "tool_call_end":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["tool_name"] = ev.get("tool_name", "")
        legacy["result"] = ev.get("result")
        legacy["error"] = ev.get("error")
        legacy["latency_ms"] = ev.get("duration_ms", 0)
    elif kind in ("llm_request", "llm_response"):
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
    return legacy


def _parse_jsonl_lines(f) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_v1_base_events(session_dir: Path) -> list[Any]:
    """Load v1 session events as typed BaseEvent instances for detector replay."""
    from autopsy.core.events import BaseEvent, event_from_dict

    out: list[BaseEvent] = []
    for payload in _load_events_jsonl(session_dir):
        try:
            out.append(event_from_dict(payload))
        except Exception:
            logger.debug("skip unparseable v1 event", exc_info=True)
    return out


def _legacy_ts_ns(ev: dict[str, Any]) -> int:
    if "timestamp_ns" in ev:
        return int(ev["timestamp_ns"])
    return int(float(ev.get("timestamp", 0)) * 1e9)


def _legacy_event_id(ev: dict[str, Any], session_id: str, seq: int) -> str:
    return str(ev.get("event_id") or ev.get("node_id") or f"{session_id}-legacy-{seq}")


def legacy_event_to_base(
    ev: dict[str, Any], *, session_id: str, seq: int,
) -> Any | None:
    """Best-effort map a legacy TraceBundle event dict to a v1 BaseEvent."""
    from autopsy.core.events import (
        AgentEndEvent,
        AgentStartEvent,
        ErrorEvent,
        EventKind,
        LLMRequestEvent,
        LLMResponseEvent,
        ToolCallEndEvent,
        ToolCallStartEvent,
    )

    if ev.get("kind"):
        try:
            from autopsy.core.events import event_from_dict
            return event_from_dict(ev)
        except Exception:
            return None

    et = ev.get("event_type", "")
    if et == "node_error":
        err_type = str(ev.get("error_type", ""))
        if err_type.startswith("detector:"):
            return None
        return ErrorEvent(
            event_id=_legacy_event_id(ev, session_id, seq),
            parent_id=ev.get("parent_node_id"),
            session_id=session_id,
            trace_id=session_id,
            timestamp_ns=_legacy_ts_ns(ev),
            kind=EventKind.ERROR,
            error_type=err_type or "Error",
            error_message=str(ev.get("error_message", "")),
            traceback=str(ev.get("traceback", "")),
            attributes=dict(ev.get("attributes") or {}),
        )
    if et == "llm_response":
        return LLMResponseEvent(
            event_id=_legacy_event_id(ev, session_id, seq),
            parent_id=ev.get("parent_node_id"),
            session_id=session_id,
            trace_id=session_id,
            timestamp_ns=_legacy_ts_ns(ev),
            kind=EventKind.LLM_RESPONSE,
            model=str(ev.get("model", "")),
            content=str(ev.get("content") or ev.get("response_text") or ""),
            tool_calls=list(ev.get("tool_calls") or []),
            prompt_tokens=int(ev.get("prompt_tokens") or 0),
            completion_tokens=int(ev.get("completion_tokens") or 0),
            total_tokens=int(ev.get("total_tokens") or 0),
            latency_ms=float(ev.get("latency_ms") or 0),
            finish_reason=str(ev.get("finish_reason") or ""),
        )
    if et == "llm_request":
        return LLMRequestEvent(
            event_id=_legacy_event_id(ev, session_id, seq),
            parent_id=ev.get("parent_node_id"),
            session_id=session_id,
            trace_id=session_id,
            timestamp_ns=_legacy_ts_ns(ev),
            kind=EventKind.LLM_REQUEST,
            model=str(ev.get("model", "")),
            messages=list(ev.get("messages") or []),
        )
    if et == "tool_call":
        return ToolCallStartEvent(
            event_id=_legacy_event_id(ev, session_id, seq),
            parent_id=ev.get("parent_node_id"),
            session_id=session_id,
            trace_id=session_id,
            timestamp_ns=_legacy_ts_ns(ev),
            kind=EventKind.TOOL_CALL_START,
            tool_name=str(ev.get("tool_name", "")),
            tool_args=dict(ev.get("tool_args") or {}),
        )
    if et == "tool_result":
        return ToolCallEndEvent(
            event_id=_legacy_event_id(ev, session_id, seq),
            parent_id=ev.get("parent_node_id"),
            session_id=session_id,
            trace_id=session_id,
            timestamp_ns=_legacy_ts_ns(ev),
            kind=EventKind.TOOL_CALL_END,
            tool_name=str(ev.get("tool_name", "")),
            result=ev.get("result"),
            error=ev.get("error"),
            duration_ms=float(ev.get("latency_ms") or ev.get("duration_ms") or 0),
        )
    if et == "node_end":
        return AgentEndEvent(
            event_id=_legacy_event_id(ev, session_id, seq),
            parent_id=ev.get("node_id"),
            session_id=session_id,
            trace_id=session_id,
            timestamp_ns=_legacy_ts_ns(ev),
            kind=EventKind.AGENT_END,
            duration_ms=float(ev.get("duration_ms") or 0),
            output_preview=str(ev.get("output_data") or ev.get("output_preview") or ""),
        )
    if et == "node_start":
        return AgentStartEvent(
            event_id=_legacy_event_id(ev, session_id, seq),
            parent_id=ev.get("parent_node_id"),
            session_id=session_id,
            trace_id=session_id,
            timestamp_ns=_legacy_ts_ns(ev),
            kind=EventKind.AGENT_START,
            agent_name=str(ev.get("node_name", "")),
            input_preview=str(ev.get("input_data") or ""),
        )
    return None


def legacy_events_to_base(
    events: list[dict[str, Any]], *, session_id: str,
) -> list[Any]:
    out = []
    for i, ev in enumerate(events):
        parsed = legacy_event_to_base(ev, session_id=session_id, seq=i)
        if parsed is not None:
            out.append(parsed)
    return sorted(out, key=lambda e: e.timestamp_ns)


def _outcome_from_bundle(bundle: dict[str, Any]) -> str:
    summary = bundle.get("summary") or {}
    status = str(summary.get("status", "success")).lower()
    if status in ("error", "failed"):
        return "error"
    if status in ("partial", "running"):
        return "partial"
    return "ok"


def load_session_events_for_detectors(
    reader: LegacyBundleReader, session_id: str,
) -> tuple[list[Any], str]:
    """Load events + outcome for detector replay (v1 dir or legacy v0 JSON)."""
    sessions = reader.root / "sessions"
    v1_dir = sessions / session_id
    if v1_dir.is_dir() and (v1_dir / "manifest.json").exists():
        try:
            manifest = json.loads((v1_dir / "manifest.json").read_text())
        except Exception:
            manifest = {}
        status = manifest.get("status", "ok")
        outcome = status if status in ("ok", "error", "partial", "live") else "ok"
        return load_v1_base_events(v1_dir), outcome
    bundle = read_v0_bundle(sessions / f"{session_id}.json")
    if bundle is None:
        raise FileNotFoundError(f"session {session_id!r} not found")
    return (
        legacy_events_to_base(bundle["events"], session_id=session_id),
        _outcome_from_bundle(bundle),
    )


def _load_events_jsonl(session_dir: Path) -> list[dict[str, Any]]:
    gz = session_dir / "events.jsonl.gz"
    plain = session_dir / "events.jsonl"
    if gz.exists():
        with gzip.open(gz, "rt", encoding="utf-8") as f:
            return _parse_jsonl_lines(f)
    if plain.exists():
        with plain.open("r", encoding="utf-8") as f:
            return _parse_jsonl_lines(f)
    return []


def read_v1_bundle(session_dir: Path) -> dict[str, Any] | None:
    """Read a v1 session directory and synthesize a legacy TraceBundle dict."""
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:
        return None

    raw_events = _load_events_jsonl(session_dir)
    legacy_events = [
        leg for e in raw_events
        if (leg := _v1_event_to_legacy(e)) is not None
    ]

    error_count = sum(1 for e in legacy_events if e.get("event_type") == "node_error")
    summary_status = {
        "ok": "success", "error": "error", "partial": "partial", "live": "partial",
    }.get(manifest.get("status", ""), "unknown")

    total_tokens = sum(
        int(e.get("total_tokens") or 0) for e in legacy_events
        if e.get("event_type") == "llm_response"
    )

    return {
        "session_id": manifest.get("session_id", ""),
        "created_at": manifest.get("start_time_ns", 0) / 1e9,
        "agent_name": manifest.get("agent_name", ""),
        "input_query": "",
        "agent_module_path": "",
        "agent_fn_name": "",
        "events": legacy_events,
        "dag_edges": [],
        "node_index": {},
        "replay_checkpoints": {},
        "summary": {
            "status": summary_status,
            "error_count": error_count,
            "total_tokens": total_tokens,
            "node_count": sum(1 for e in legacy_events if e.get("event_type") == "node_start"),
            "total_duration_ms": manifest.get("duration_ms", 0) or 0,
        },
    }


class LegacyBundleReader:
    """Bilingual reader that returns the old TraceBundle dict shape.

    `root` is the session root that contains either v0 files
    (`sessions/<id>.json`) or v1 directories (`sessions/<id>/manifest.json`),
    or both.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        sessions = self.root / "sessions"
        if not sessions.exists():
            return out
        for child in sessions.iterdir():
            if child.is_file() and child.suffix == ".json" and not child.name.startswith("sessions_index"):
                bundle = read_v0_bundle(child)
                if bundle is not None:
                    out.append({
                        "session_id": bundle["session_id"],
                        "agent_name": bundle["agent_name"],
                        "created_at": bundle["created_at"],
                        "summary": bundle["summary"],
                    })
            elif child.is_dir() and (child / "manifest.json").exists():
                try:
                    manifest = json.loads((child / "manifest.json").read_text())
                except Exception:
                    continue
                if int(manifest.get("autopsy_format_version", 1)) != 1:
                    continue
                manifest_status = manifest.get("status", "")
                mapped_status = {
                    "ok": "success", "error": "error",
                    "partial": "partial", "live": "running",
                }.get(manifest_status, "unknown")
                error_type = manifest.get("error_type") or ""
                out.append({
                    "session_id": manifest.get("session_id", child.name),
                    "agent_name": manifest.get("agent_name", ""),
                    "created_at": manifest.get("start_time_ns", 0) / 1e9,
                    "status": mapped_status,
                    "node_count": manifest.get("event_count", 0),
                    "error_count": 1 if manifest_status == "error" else 0,
                    "error_type": error_type,
                    "summary": {
                        "status": mapped_status,
                        "error_count": 1 if manifest_status == "error" else 0,
                        "node_count": manifest.get("event_count", 0),
                        "error_type": error_type,
                    },
                })
        out.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return out

    def load(self, session_id: str) -> dict[str, Any] | None:
        sessions = self.root / "sessions"
        v1_dir = sessions / session_id
        if v1_dir.is_dir() and (v1_dir / "manifest.json").exists():
            try:
                manifest = json.loads((v1_dir / "manifest.json").read_text())
            except Exception:
                return None
            v = int(manifest.get("autopsy_format_version", 1))
            if v != 1:
                raise UnknownSchemaVersionError(v, str(v1_dir))
            return read_v1_bundle(v1_dir)
        v0_path = sessions / f"{session_id}.json"
        return read_v0_bundle(v0_path)
