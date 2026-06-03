"""Verify each consumer of the legacy TraceBundle works against v1 sessions.

Concretely: write one v1 session via the writer, then call the same code
paths the dashboard / diagnostics / replay engine use, and assert they
produce sane outputs.
"""
from __future__ import annotations

import time
from pathlib import Path

from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.events import AgentEndEvent, AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def _write_v1(tmp_path: Path, sid: str) -> None:
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(sid, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000A", parent_id=None,
            session_id=sid, trace_id=sid, timestamp_ns=1,
            kind=EventKind.AGENT_START, agent_name="a",
        ))
        w.enqueue(AgentEndEvent(
            event_id="01HXY00000000000000000000B",
            parent_id="01HXY00000000000000000000A",
            session_id=sid, trace_id=sid, timestamp_ns=2,
            kind=EventKind.AGENT_END, duration_ms=1.0,
        ))
        w.end_session(sid, outcome="ok")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / sid / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)


def test_dashboard_listing_works_off_legacy_reader(tmp_path):
    _write_v1(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    rows = reader.list()
    assert rows
    assert rows[0]["session_id"] == "01HXY000000000000000000001"


def test_diagnose_load_works_off_legacy_reader(tmp_path):
    _write_v1(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    bundle = reader.load("01HXY000000000000000000001")
    assert bundle is not None
    assert any(e["event_type"] == "node_start" for e in bundle["events"])
    assert bundle["node_index"]
    start_id = next(
        e["node_id"] for e in bundle["events"] if e["event_type"] == "node_start"
    )
    assert bundle["node_index"][start_id].get("end_event")
