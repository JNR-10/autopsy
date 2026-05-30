"""Reindex rebuilds the SQLite index from manifests on disk."""
from __future__ import annotations

import time

from autopsy.core.config import LensConfig
from autopsy.core.events import AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def _write_session(root, sid):
    store = LocalFilesystemStore(root=root)
    cfg = LensConfig(session_dir=str(root))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(sid, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=sid, trace_id=sid,
            timestamp_ns=1, kind=EventKind.AGENT_START, agent_name="a",
        ))
        w.end_session(sid, outcome="ok")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (root / "sessions" / sid / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)


def test_reindex_rebuilds_from_manifests(tmp_path):
    _write_session(tmp_path, "01HXY000000000000000000001")
    _write_session(tmp_path, "01HXY000000000000000000002")

    (tmp_path / "index.sqlite").unlink()
    store = LocalFilesystemStore(root=tmp_path)
    n = store.reindex()
    assert n == 2
    ids = {r["session_id"] for r in store.list_sessions()}
    assert ids == {
        "01HXY000000000000000000001",
        "01HXY000000000000000000002",
    }
