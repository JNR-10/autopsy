"""Tests for reading v1 sessions into the legacy TraceBundle dict shape."""
from __future__ import annotations

import time

import pytest

from autopsy.core.compat import read_v1_bundle
from autopsy.core.config import LensConfig
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
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def _ev(cls, kind, **extra):
    base = dict(
        event_id="01HXY00000000000000000000" + str(extra.pop("seq", "0")),
        parent_id=extra.pop("parent_id", None),
        session_id=SID,
        trace_id=SID,
        timestamp_ns=extra.pop("ts", 1),
        kind=kind,
    )
    return cls(**base, **extra)


@pytest.fixture
def written_session(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(_ev(AgentStartEvent, EventKind.AGENT_START, agent_name="a", seq="1"))
        w.enqueue(_ev(LLMRequestEvent, EventKind.LLM_REQUEST,
                      model="m", messages=[], temperature=1.0, max_tokens=0,
                      tools=[], prompt_tokens_estimate=0, seq="2"))
        w.enqueue(_ev(LLMResponseEvent, EventKind.LLM_RESPONSE,
                      model="m", content="hi", tool_calls=[],
                      prompt_tokens=1, completion_tokens=2, total_tokens=3,
                      latency_ms=1.0, finish_reason="stop", seq="3"))
        w.enqueue(_ev(ToolCallStartEvent, EventKind.TOOL_CALL_START,
                      tool_name="t", tool_args={"a": 1}, seq="4"))
        w.enqueue(_ev(ToolCallEndEvent, EventKind.TOOL_CALL_END,
                      tool_name="t", result="r", error=None, duration_ms=1.0, seq="5"))
        w.enqueue(_ev(ErrorEvent, EventKind.ERROR,
                      error_type="X", error_message="m", traceback="t", seq="6"))
        w.enqueue(_ev(AgentEndEvent, EventKind.AGENT_END, duration_ms=10.0, seq="7"))
        w.end_session(SID, outcome="error", error_type="X")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / SID / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)
    return tmp_path / "sessions" / SID


def test_v1_reader_produces_legacy_event_types(written_session):
    bundle = read_v1_bundle(written_session)
    assert bundle is not None
    types_present = {e["event_type"] for e in bundle["events"]}
    assert {"node_start", "node_end", "llm_request", "llm_response",
            "tool_call", "tool_result", "node_error"} <= types_present


def test_v1_reader_carries_summary_status(written_session):
    bundle = read_v1_bundle(written_session)
    assert bundle["summary"]["status"] == "error"
    assert bundle["summary"]["error_count"] >= 1


def test_v1_reader_returns_none_for_missing(tmp_path):
    assert read_v1_bundle(tmp_path / "nope") is None
