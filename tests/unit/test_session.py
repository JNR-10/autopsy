"""Tests for the new Session lifecycle."""
from __future__ import annotations

import time


from autopsy.core.config import LensConfig
from autopsy.core.session import Session, get_writer
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def test_session_id_is_ulid():
    cfg = LensConfig()
    s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
    assert len(s.session_id) == 26
    s.end(outcome="ok")


def test_record_event_enqueues_through_writer(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    writer = Writer(config=cfg, store=store)
    writer.start()
    try:
        s = Session.begin(
            config=cfg, agent_name="a", sample=SampleMode.ALL, writer=writer,
        )
        from autopsy.core.events import EventKind, LogEvent
        ev = LogEvent(
            event_id="01HXY000000000000000000001",
            parent_id=None,
            session_id=s.session_id,
            trace_id=s.session_id,
            timestamp_ns=1,
            kind=EventKind.LOG,
            name="n",
        )
        s.record_event(ev)
        s.end(outcome="ok")
        time.sleep(0.2)
        assert (tmp_path / "sessions" / s.session_id / "manifest.json").exists()
    finally:
        writer.shutdown(timeout=2.0)


def test_get_writer_returns_singleton():
    a = get_writer(LensConfig())
    b = get_writer(LensConfig())
    assert a is b


def test_session_record_event_never_raises():
    cfg = LensConfig()
    s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)

    class Bomb:
        session_id = "wrong"
        kind = None

    s.record_event(Bomb())  # type: ignore[arg-type]
    s.end(outcome="ok")
