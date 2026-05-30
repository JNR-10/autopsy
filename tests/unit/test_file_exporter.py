"""Tests for FileSystemExporter wrapping LocalFilesystemStore."""
from __future__ import annotations

from autopsy.core.events import (
    AgentStartEvent,
    EventKind,
    Manifest,
)
from autopsy.core.exporters.file import FileSystemExporter
from autopsy.core.store.local_fs import LocalFilesystemStore


SID = "01HXY000000000000000000001"


def _ev():
    return AgentStartEvent(
        event_id="01HXY000000000000000000001",
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=1,
        kind=EventKind.AGENT_START,
        agent_name="a",
    )


def _manifest():
    return Manifest(
        session_id=SID,
        agent_name="a",
        start_time_ns=1,
        end_time_ns=2,
        duration_ms=0.001,
        status="ok",
        error_type=None,
        event_count=1,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=1,
        monotonic_ns_at_start=1,
    )


def test_export_writes_events(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    exp = FileSystemExporter(store=store)
    exp.export(SID, [_ev()])
    assert (tmp_path / "sessions" / SID / "events.jsonl").exists()


def test_finalize_seals_manifest(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    exp = FileSystemExporter(store=store)
    exp.export(SID, [_ev()])
    exp.finalize_session(_manifest())
    assert (tmp_path / "sessions" / SID / "manifest.json").exists()


def test_finalize_swallows_store_errors(tmp_path):
    class BrokenStore:
        def write_events(self, *a, **k): raise IOError("boom")
        def finalize_session(self, *a, **k): raise IOError("boom")

    exp = FileSystemExporter(store=BrokenStore())
    exp.export(SID, [_ev()])
    exp.finalize_session(_manifest())
