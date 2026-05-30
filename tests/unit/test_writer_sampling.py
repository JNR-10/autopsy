"""Tests for the sample state machine in the writer."""
from __future__ import annotations

import time


from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import (
    AgentEndEvent,
    AgentStartEvent,
    ErrorEvent,
    EventKind,
    LogEvent,
)
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


SID = "01HXY000000000000000000001"


def _agent_start(seq=0):
    return AgentStartEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.AGENT_START,
        agent_name="a",
    )


def _agent_end(seq=99):
    return AgentEndEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.AGENT_END,
        duration_ms=1.0,
    )


def _log(seq, **attrs):
    return LogEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.LOG,
        name="n",
        attributes=attrs,
    )


def _error(seq=98):
    return ErrorEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.ERROR,
        error_type="X",
        error_message="m",
        traceback="t",
    )


def _wait_for_session_finalized(store, sid, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (store.root / "sessions" / sid / "manifest.json").exists():
            return True
        time.sleep(0.01)
    return False


def test_sample_errors_success_writes_no_disk_artifact(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        for i in range(3):
            w.enqueue(_log(i + 1))
        w.enqueue(_agent_end())
        w.end_session(SID, outcome="ok")
        time.sleep(0.2)
    finally:
        w.shutdown(timeout=2.0)
    assert not (tmp_path / "sessions" / SID).exists()


def test_sample_errors_error_writes_session(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        w.enqueue(_log(1))
        w.enqueue(_error())
        w.enqueue(_agent_end())
        w.end_session(SID, outcome="error", error_type="X")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "error"
    assert len(payload["events"]) >= 3


def test_sample_all_writes_session_even_on_success(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(_log(1))
        w.end_session(SID, outcome="ok")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "ok"


def test_sample_off_creates_nothing(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.OFF, agent_name="a", start_ns=1)
        w.enqueue(_log(1))
        w.end_session(SID, outcome="ok")
        time.sleep(0.1)
    finally:
        w.shutdown(timeout=2.0)
    assert not (tmp_path / "sessions" / SID).exists()


def test_in_flight_buffer_cap_promotes_to_partial(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        max_in_flight_buffer_mb=0,
    )
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        for i in range(50):
            w.enqueue(_log(i + 1, payload="x" * 4096))
        w.end_session(SID, outcome="ok")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "partial"


def test_head_rate_promotes_session(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            SID, sample=SampleMode.RATE, agent_name="a", start_ns=1,
            head_keep=True,
        )
        w.enqueue(_log(1))
        w.end_session(SID, outcome="ok")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "ok"
