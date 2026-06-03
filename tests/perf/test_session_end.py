"""Session-end path benchmarks (detector merge + evaluation cap)."""
from __future__ import annotations

import time

import pytest

import autopsy.core.session as session_mod
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent, ToolCallStartEvent
from autopsy.core.session import Session


def _tool_event(i: int, session_id: str) -> ToolCallStartEvent:
    return ToolCallStartEvent(
        event_id=f"01HXY0000000000000{i:06d}",
        parent_id=None,
        session_id=session_id,
        trace_id=session_id,
        timestamp_ns=i,
        kind=EventKind.TOOL_CALL_START,
        tool_name="search",
        tool_args={"i": i},
    )


@pytest.mark.slow
def test_events_for_detectors_merge_1k_under_50ms(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        detector_full_trace=False,
        max_detector_eval_events=8192,
    )
    s = Session.begin(config=cfg, agent_name="a", sample="all")
    for i in range(1000):
        s.record_event(_tool_event(i, s.session_id))
    t0 = time.perf_counter()
    events = s.events_for_detectors()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert len(events) == 1000
    assert elapsed_ms < 500.0, f"merge took {elapsed_ms:.1f}ms"


@pytest.mark.slow
def test_events_for_detectors_cap_limits_input(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        max_detector_eval_events=100,
    )
    s = Session.begin(config=cfg, agent_name="a", sample="all")
    for i in range(500):
        s.record_event(_tool_event(i, s.session_id))
    events = s.events_for_detectors()
    assert len(events) == 100
    assert events[0].timestamp_ns == 400
    assert events[-1].timestamp_ns == 499


@pytest.mark.slow
def test_session_end_with_detectors_under_200ms(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        enabled_detectors=["tool_failure"],
        detector_full_trace=False,
    )
    s = Session.begin(config=cfg, agent_name="a", sample="all")
    for i in range(200):
        s.record_event(LogEvent(
            event_id=f"01HXY0000000000000{i:06d}",
            parent_id=None,
            session_id=s.session_id,
            trace_id=s.session_id,
            timestamp_ns=i,
            kind=EventKind.LOG,
            name="step",
        ))
    t0 = time.perf_counter()
    s.end(outcome="ok")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 200.0, f"end() took {elapsed_ms:.1f}ms"
