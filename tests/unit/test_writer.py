"""Unit tests for Writer enqueue + drop-on-full semantics (no disk yet)."""
from __future__ import annotations

import time


from autopsy.core.config import LensConfig
from autopsy.core.events import (
    AgentStartEvent,
    EventKind,
    LogEvent,
)
from autopsy.core.writer import Writer


def _ev(kind, sid, seq=0):
    base = dict(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=seq,
        kind=kind,
    )
    if kind is EventKind.AGENT_START:
        return AgentStartEvent(**base, agent_name="a")
    return LogEvent(**base, name="n")


def test_writer_starts_and_stops_cleanly(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg)
    w.start()
    assert w.is_alive()
    w.shutdown(timeout=2.0)
    assert not w.is_alive()


def test_enqueue_increments_dropped_counter_when_full(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), queue_maxsize=4)
    w = Writer(config=cfg)
    w.start()
    try:
        w.pause_drain()
        for i in range(20):
            w.enqueue(_ev(EventKind.LOG, "s", seq=i))
        assert w.dropped_events_total >= 10
    finally:
        w.resume_drain()
        w.shutdown(timeout=2.0)


def test_enqueue_never_blocks_host_thread(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), queue_maxsize=2)
    w = Writer(config=cfg)
    w.start()
    try:
        w.pause_drain()
        t0 = time.perf_counter()
        for i in range(1000):
            w.enqueue(_ev(EventKind.LOG, "s", seq=i))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 100, f"enqueue blocked: {elapsed_ms}ms"
    finally:
        w.resume_drain()
        w.shutdown(timeout=2.0)


def test_drained_events_arrive_in_order(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(50):
            w.enqueue(_ev(EventKind.LOG, "s", seq=i))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and w.drained_count_for_test("s") < 50:
            time.sleep(0.01)
        events = w.drained_events_for_test("s")
        assert len(events) == 50
        assert [e.timestamp_ns for e in events] == list(range(50))
    finally:
        w.shutdown(timeout=2.0)
