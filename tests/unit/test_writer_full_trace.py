"""Writer flush_now + accumulated events for detector full trace."""
from __future__ import annotations

from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def test_flush_now_drains_queue_into_accumulated(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=None)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        for i in range(5):
            w.enqueue(LogEvent(
                event_id=f"01HXY00000000000000000{i:04d}",
                parent_id=None, session_id=SID, trace_id=SID,
                timestamp_ns=i, kind=EventKind.LOG, name=str(i),
            ))
        n = w.flush_session_now(SID)
        assert n >= 5
        acc = w.accumulated_events_for_session(SID)
        assert len(acc) >= 5
    finally:
        w.shutdown(timeout=2.0)
