"""Detector evaluation cap applied at session end."""
from __future__ import annotations

import autopsy.core.session as session_mod
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, ToolCallStartEvent
from autopsy.core.session import Session


def test_end_respects_max_detector_eval_events(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        enabled_detectors=[],
        max_detector_eval_events=2,
    )
    s = Session.begin(config=cfg, agent_name="a", sample="all")
    for i in range(5):
        s.record_event(ToolCallStartEvent(
            event_id=f"01HXY0000000000000{i:06d}",
            parent_id=None,
            session_id=s.session_id,
            trace_id=s.session_id,
            timestamp_ns=i,
            kind=EventKind.TOOL_CALL_START,
            tool_name="t",
            tool_args={},
        ))
    events = s.events_for_detectors()
    assert len(events) == 2
    assert [e.timestamp_ns for e in events] == [3, 4]
