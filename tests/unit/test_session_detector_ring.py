"""Detector ring retains tool/LLM events when capture buffer is tiny."""
from __future__ import annotations

import autopsy.core.session as session_mod
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent, ToolCallStartEvent
from autopsy.core.session import Session


def test_detector_ring_keeps_tools_when_capture_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(
        default_sample="errors",
        max_capture_buffer_events=2,
        max_detector_ring_events=100,
    )
    s = Session.begin(config=cfg, agent_name="a", sample="errors")
    for i in range(10):
        s.record_event(LogEvent(
            event_id=f"01HXY00000000000000000{i:04d}",
            parent_id=None,
            session_id=s.session_id,
            trace_id=s.session_id,
            timestamp_ns=i,
            kind=EventKind.LOG,
            name="noise",
        ))
    s.record_event(ToolCallStartEvent(
        event_id="01HXY00000000000000000099",
        parent_id=None,
        session_id=s.session_id,
        trace_id=s.session_id,
        timestamp_ns=99,
        kind=EventKind.TOOL_CALL_START,
        tool_name="search",
        tool_args={},
    ))
    events = s.events_for_detectors()
    tool_events = [e for e in events if e.kind is EventKind.TOOL_CALL_START]
    assert len(tool_events) == 1
