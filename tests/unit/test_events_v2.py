"""Unit tests for the v1 Pydantic event models."""
from __future__ import annotations

import json

import pytest

from autopsy.core.events_v2 import (
    AgentEndEvent,
    AgentStartEvent,
    AttachmentRefEvent,
    BaseEvent,
    ErrorEvent,
    EventKind,
    LLMRequestEvent,
    LLMResponseEvent,
    LogEvent,
    Manifest,
    SessionEndEvent,
    SessionStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    event_from_dict,
)


def _base_kwargs(kind: EventKind, **extra):
    return dict(
        event_id="01HXY000000000000000000000",
        parent_id=None,
        session_id="01HXY000000000000000000000",
        trace_id="01HXY000000000000000000000",
        timestamp_ns=1,
        kind=kind,
        **extra,
    )


def test_base_event_envelope_round_trips():
    ev = BaseEvent(**_base_kwargs(EventKind.LOG))
    d = ev.model_dump()
    assert d["kind"] == "log"
    assert d["status"] == "unset"
    assert json.loads(json.dumps(d))["event_id"] == "01HXY000000000000000000000"


def test_session_start_event_carries_agent_name():
    ev = SessionStartEvent(
        **_base_kwargs(EventKind.SESSION_START),
        agent_name="my_agent",
        input_query="hello",
        wall_clock_ns=2,
        monotonic_ns=1,
        autopsy_format_version=1,
    )
    d = ev.model_dump()
    assert d["kind"] == "session_start"
    assert d["agent_name"] == "my_agent"
    assert d["autopsy_format_version"] == 1


def test_event_kinds_are_closed_at_version_1():
    expected = {
        "session_start", "session_end",
        "agent_start", "agent_end",
        "llm_request", "llm_response",
        "tool_call_start", "tool_call_end",
        "error", "log", "attachment_ref", "detector_verdict",
    }
    assert {k.value for k in EventKind} == expected


def test_event_from_dict_dispatches_on_kind():
    payload = AgentStartEvent(
        **_base_kwargs(EventKind.AGENT_START),
        agent_name="x",
    ).model_dump()
    ev = event_from_dict(payload)
    assert isinstance(ev, AgentStartEvent)
    assert ev.agent_name == "x"


def test_event_from_dict_rejects_unknown_kind():
    payload = BaseEvent(**_base_kwargs(EventKind.LOG)).model_dump()
    payload["kind"] = "not_a_real_kind"
    with pytest.raises(ValueError):
        event_from_dict(payload)


def test_llm_response_event_fields():
    ev = LLMResponseEvent(
        **_base_kwargs(EventKind.LLM_RESPONSE),
        model="gpt-4o",
        content="hi",
        tool_calls=[],
        prompt_tokens=1,
        completion_tokens=2,
        total_tokens=3,
        latency_ms=4.0,
        finish_reason="stop",
    )
    assert ev.model_dump()["total_tokens"] == 3


def test_attachment_ref_records_hash_and_preview():
    ev = AttachmentRefEvent(
        **_base_kwargs(EventKind.ATTACHMENT_REF),
        field_path="messages[0].content",
        sha256="a" * 64,
        size_bytes=99999,
        preview="hello...",
    )
    assert ev.sha256 == "a" * 64


def test_error_event_carries_traceback():
    ev = ErrorEvent(
        **_base_kwargs(EventKind.ERROR),
        error_type="ValueError",
        error_message="bad",
        traceback="trace",
    )
    assert ev.error_type == "ValueError"


def test_log_event_attributes_pass_through():
    ev = LogEvent(
        **_base_kwargs(EventKind.LOG),
        name="retry",
        attributes={"attempt": 3, "reason": "rate_limited"},
    )
    assert ev.attributes["attempt"] == 3


def test_manifest_round_trips():
    m = Manifest(
        session_id="01HXY000000000000000000000",
        agent_name="agent",
        start_time_ns=1,
        end_time_ns=None,
        duration_ms=None,
        status="live",
        error_type=None,
        event_count=0,
        dropped_events=0,
        pinned=False,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=2,
        monotonic_ns_at_start=1,
    )
    s = m.model_dump_json()
    again = Manifest.model_validate_json(s)
    assert again.session_id == m.session_id
    assert again.status == "live"


@pytest.mark.parametrize("cls,kind", [
    (SessionStartEvent, EventKind.SESSION_START),
    (SessionEndEvent, EventKind.SESSION_END),
    (AgentStartEvent, EventKind.AGENT_START),
    (AgentEndEvent, EventKind.AGENT_END),
    (LLMRequestEvent, EventKind.LLM_REQUEST),
    (LLMResponseEvent, EventKind.LLM_RESPONSE),
    (ToolCallStartEvent, EventKind.TOOL_CALL_START),
    (ToolCallEndEvent, EventKind.TOOL_CALL_END),
    (ErrorEvent, EventKind.ERROR),
    (LogEvent, EventKind.LOG),
    (AttachmentRefEvent, EventKind.ATTACHMENT_REF),
])
def test_every_event_kind_round_trips_through_event_from_dict(cls, kind):
    fields = {}
    if cls is SessionStartEvent:
        fields = dict(agent_name="a", input_query="q", wall_clock_ns=1, monotonic_ns=1, autopsy_format_version=1)
    elif cls is SessionEndEvent:
        fields = dict(duration_ms=1.0, event_count=1, dropped_events=0, final_status="ok")
    elif cls is AgentStartEvent:
        fields = dict(agent_name="a")
    elif cls is AgentEndEvent:
        fields = dict(duration_ms=1.0)
    elif cls is LLMRequestEvent:
        fields = dict(model="m", messages=[], temperature=1.0, max_tokens=0, tools=[], prompt_tokens_estimate=0)
    elif cls is LLMResponseEvent:
        fields = dict(model="m", content="", tool_calls=[], prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_ms=0.0, finish_reason="stop")
    elif cls is ToolCallStartEvent:
        fields = dict(tool_name="t", tool_args={})
    elif cls is ToolCallEndEvent:
        fields = dict(tool_name="t", result=None, error=None, duration_ms=0.0)
    elif cls is ErrorEvent:
        fields = dict(error_type="E", error_message="m", traceback="t")
    elif cls is LogEvent:
        fields = dict(name="n", attributes={})
    elif cls is AttachmentRefEvent:
        fields = dict(field_path="f", sha256="a" * 64, size_bytes=1, preview="")
    ev = cls(**_base_kwargs(kind), **fields)
    again = event_from_dict(ev.model_dump())
    assert type(again) is cls
    assert again.kind is kind
