"""Pydantic v2 event models for the capture layer (schema version 1).

These models replace the dataclass-based models in `events.py`. They live
under a `_v2` filename until phase 7, at which point this file becomes
`events.py`. The original models keep working alongside this one so the
dashboard, diagnostics, and replay engine continue to consume the existing
`TraceBundle` shape until the bilingual `LegacyBundleReader` is in place.

Invariants:
- Every event carries the BaseEvent envelope: event_id, parent_id,
  session_id, trace_id, timestamp_ns, kind, status, attributes.
- `kind` is a closed enum at schema version 1.
- All models use ConfigDict(extra="forbid") so typos are caught early.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventKind(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    ERROR = "error"
    LOG = "log"
    ATTACHMENT_REF = "attachment_ref"
    DETECTOR_VERDICT = "detector_verdict"


Status = Literal["ok", "error", "unset"]


class BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    parent_id: str | None = None
    session_id: str
    trace_id: str
    timestamp_ns: int
    kind: EventKind
    status: Status = "unset"
    attributes: dict[str, Any] = Field(default_factory=dict)


class SessionStartEvent(BaseEvent):
    agent_name: str
    input_query: str = ""
    wall_clock_ns: int
    monotonic_ns: int
    autopsy_format_version: int = 1


class SessionEndEvent(BaseEvent):
    duration_ms: float
    event_count: int
    dropped_events: int
    final_status: Literal["ok", "error", "partial"]


class AgentStartEvent(BaseEvent):
    agent_name: str
    role: str = "agent"
    input_preview: str = ""


class AgentEndEvent(BaseEvent):
    duration_ms: float
    output_preview: str = ""
    output_hash: str = ""


class LLMRequestEvent(BaseEvent):
    model: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 1.0
    max_tokens: int = 0
    tools: list[dict[str, Any]] = Field(default_factory=list)
    prompt_tokens_estimate: int = 0


class LLMResponseEvent(BaseEvent):
    model: str
    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = ""


class ToolCallStartEvent(BaseEvent):
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)


class ToolCallEndEvent(BaseEvent):
    tool_name: str
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class ErrorEvent(BaseEvent):
    error_type: str
    error_message: str
    traceback: str


class LogEvent(BaseEvent):
    name: str


class AttachmentRefEvent(BaseEvent):
    field_path: str
    sha256: str
    size_bytes: int
    preview: str = ""


class DetectorVerdictEvent(BaseEvent):
    detector_name: str
    verdict: Literal["pass", "fail", "warn"]
    score: float = 0.0
    reason: str = ""


_KIND_TO_CLASS: dict[EventKind, type[BaseEvent]] = {
    EventKind.SESSION_START: SessionStartEvent,
    EventKind.SESSION_END: SessionEndEvent,
    EventKind.AGENT_START: AgentStartEvent,
    EventKind.AGENT_END: AgentEndEvent,
    EventKind.LLM_REQUEST: LLMRequestEvent,
    EventKind.LLM_RESPONSE: LLMResponseEvent,
    EventKind.TOOL_CALL_START: ToolCallStartEvent,
    EventKind.TOOL_CALL_END: ToolCallEndEvent,
    EventKind.ERROR: ErrorEvent,
    EventKind.LOG: LogEvent,
    EventKind.ATTACHMENT_REF: AttachmentRefEvent,
    EventKind.DETECTOR_VERDICT: DetectorVerdictEvent,
}


def event_from_dict(payload: dict[str, Any]) -> BaseEvent:
    """Construct the right event subclass from a dict by inspecting `kind`."""
    raw_kind = payload.get("kind")
    try:
        kind = EventKind(raw_kind)
    except ValueError as exc:
        raise ValueError(f"unknown event kind: {raw_kind!r}") from exc
    cls = _KIND_TO_CLASS[kind]
    return cls.model_validate(payload)


class Manifest(BaseModel):
    """Per-session manifest.json. Written at session start, rewritten at finalize."""
    model_config = ConfigDict(extra="forbid")

    session_id: str
    agent_name: str
    start_time_ns: int
    end_time_ns: int | None = None
    duration_ms: float | None = None
    status: Literal["live", "ok", "error", "partial"]
    error_type: str | None = None
    event_count: int = 0
    dropped_events: int = 0
    pinned: bool = False
    autopsy_format_version: int = 1
    autopsy_version: str
    wall_clock_ns_at_start: int
    monotonic_ns_at_start: int
    extra: dict[str, Any] = Field(default_factory=dict)
