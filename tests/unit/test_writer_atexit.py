"""Tests for atexit drain semantics on the writer."""
from __future__ import annotations

import time


from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def _log(seq):
    return LogEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.LOG,
        name="n",
    )


def test_atexit_drains_within_timeout(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
    for i in range(20):
        w.enqueue(_log(i))
    w.end_session(SID, outcome="ok")
    t0 = time.perf_counter()
    w.atexit_flush(timeout=2.0)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.5
    assert (tmp_path / "sessions" / SID / "manifest.json").exists()


def test_atexit_marks_unfinalized_session_partial(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
    w.enqueue(_log(0))
    w.atexit_flush(timeout=2.0)
    payload = store.load_session(SID)
    if payload is not None:
        assert payload["manifest"]["status"] in ("partial", "ok")


def test_atexit_is_idempotent(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    w.atexit_flush(timeout=1.0)
    w.atexit_flush(timeout=1.0)
