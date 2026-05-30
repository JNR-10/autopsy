from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent
from autopsy.core.session import Session
from autopsy.core.writer import SampleMode

SID = "01HXY000000000000000000001"


def test_record_event_buffers_without_writer():
    cfg = LensConfig(default_sample="errors", max_capture_buffer_events=10)
    s = Session(
        session_id=SID, agent_name="a", sample=SampleMode.ERRORS,
        head_keep=False, writer=None, config=cfg,
        start_perf_ns=1, wall_ns=1,
    )
    ev = LogEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None, session_id=SID, trace_id=SID,
        timestamp_ns=1, kind=EventKind.LOG, name="x",
    )
    s.record_event(ev)
    assert len(s.capture_events()) == 1


def test_buffer_respects_max_events():
    cfg = LensConfig(default_sample="errors", max_capture_buffer_events=2)
    s = Session(
        session_id=SID, agent_name="a", sample=SampleMode.ERRORS,
        head_keep=False, writer=None, config=cfg,
        start_perf_ns=1, wall_ns=1,
    )
    for i in range(5):
        s.record_event(LogEvent(
            event_id=f"01HXY0000000000000000000{i:02d}",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=i, kind=EventKind.LOG, name=str(i),
        ))
    assert len(s.capture_events()) == 2
