"""Tests for the unified bilingual LegacyBundleReader."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import AgentEndEvent, AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def _write_v0_session(root: Path, session_id: str) -> None:
    sessions = root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sessions.joinpath(f"{session_id}.json").write_text(json.dumps({
        "session_id": session_id, "created_at": 1700000000.0,
        "agent_name": "old", "input_query": "q",
        "events": [{"event_type": "session_start", "session_id": session_id}],
        "summary": {"status": "success", "error_count": 0},
    }))


def _write_v1_session(root: Path, session_id: str) -> None:
    store = LocalFilesystemStore(root=root)
    cfg = LensConfig(session_dir=str(root))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(session_id, sample=SampleMode.ALL, agent_name="new", start_ns=1)
        ev1 = AgentStartEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=session_id, trace_id=session_id,
            timestamp_ns=1, kind=EventKind.AGENT_START, agent_name="new",
        )
        ev2 = AgentEndEvent(
            event_id="01HXY00000000000000000000B",
            parent_id=None, session_id=session_id, trace_id=session_id,
            timestamp_ns=2, kind=EventKind.AGENT_END, duration_ms=1.0,
        )
        w.enqueue(ev1)
        w.enqueue(ev2)
        w.end_session(session_id, outcome="ok")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (root / "sessions" / session_id / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)


def test_reader_lists_v0_and_v1_sessions_together(tmp_path):
    _write_v0_session(tmp_path, "old-1")
    _write_v1_session(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    rows = reader.list()
    ids = {r["session_id"] for r in rows}
    assert ids == {"old-1", "01HXY000000000000000000001"}


def test_reader_load_returns_v0(tmp_path):
    _write_v0_session(tmp_path, "old-1")
    reader = LegacyBundleReader(root=tmp_path)
    bundle = reader.load("old-1")
    assert bundle is not None
    assert bundle["agent_name"] == "old"


def test_reader_load_returns_v1_translated(tmp_path):
    _write_v1_session(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    bundle = reader.load("01HXY000000000000000000001")
    assert bundle is not None
    types = {e["event_type"] for e in bundle["events"]}
    assert "node_start" in types
    assert "node_end" in types


def test_reader_load_missing_returns_none(tmp_path):
    reader = LegacyBundleReader(root=tmp_path)
    assert reader.load("nope") is None


def test_reader_refuses_unknown_future_version(tmp_path):
    sid = "01HXY000000000000000000001"
    sd = tmp_path / "sessions" / sid
    sd.mkdir(parents=True)
    (sd / "manifest.json").write_text(json.dumps({
        "session_id": sid, "agent_name": "x", "start_time_ns": 1,
        "status": "ok", "autopsy_format_version": 999,
        "autopsy_version": "9.9.9",
        "wall_clock_ns_at_start": 1, "monotonic_ns_at_start": 1,
    }))
    reader = LegacyBundleReader(root=tmp_path)
    with pytest.raises(Exception) as excinfo:
        reader.load(sid)
    assert "999" in str(excinfo.value)
    assert "autopsy migrate" in str(excinfo.value)
