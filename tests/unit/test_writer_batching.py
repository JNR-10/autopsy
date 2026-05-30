"""Tests for writer batching and redaction integration."""
from __future__ import annotations

import time


from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import EventKind, LogEvent
from autopsy.core.writer import Writer


def _log(sid, seq, **attrs):
    return LogEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=seq,
        kind=EventKind.LOG,
        name="n",
        attributes=attrs,
    )


def test_redactor_is_applied_to_each_event(tmp_path):
    seen = []

    def red(ev):
        seen.append(ev.attributes.get("k"))
        return ev.model_copy(update={"attributes": {"k": "REDACTED"}})

    cfg = LensConfig(session_dir=str(tmp_path), redactor=red)
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(5):
            w.enqueue(_log("s", i, k=f"orig-{i}"))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and w.drained_count_for_test("s") < 5:
            time.sleep(0.01)
        events = w.drained_events_for_test("s")
        assert all(e.attributes == {"k": "REDACTED"} for e in events)
        assert set(seen) == {f"orig-{i}" for i in range(5)}
    finally:
        w.shutdown(timeout=2.0)


def test_redactor_returning_none_drops_event(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), redactor=lambda ev: None)
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(10):
            w.enqueue(_log("s", i))
        time.sleep(0.2)
        assert w.drained_count_for_test("s") == 0
    finally:
        w.shutdown(timeout=2.0)


def test_redactor_that_raises_is_caught_and_drops(tmp_path):
    def red(ev):
        raise RuntimeError("boom")

    cfg = LensConfig(session_dir=str(tmp_path), redactor=red)
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(5):
            w.enqueue(_log("s", i))
        time.sleep(0.2)
        assert w.drained_count_for_test("s") == 0
        assert w.is_alive()
    finally:
        w.shutdown(timeout=2.0)


def test_batch_respects_flush_interval(tmp_path):
    cfg = LensConfig(
        session_dir=str(tmp_path), flush_batch_size=1000, flush_interval_ms=30,
    )
    w = Writer(config=cfg)
    w.start()
    try:
        w.enqueue(_log("s", 0))
        time.sleep(0.1)
        assert w.drained_count_for_test("s") == 1
    finally:
        w.shutdown(timeout=2.0)


def test_batch_respects_size_cap(tmp_path):
    cfg = LensConfig(
        session_dir=str(tmp_path), flush_batch_size=5, flush_interval_ms=10_000,
    )
    w = Writer(config=cfg)
    w.start()
    try:
        w.pause_drain()
        for i in range(13):
            w.enqueue(_log("s", i))
        w.resume_drain()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and w.drained_count_for_test("s") < 13:
            time.sleep(0.01)
        assert w.drained_count_for_test("s") == 13
    finally:
        w.shutdown(timeout=2.0)
