"""Unit tests for LocalFilesystemStore."""
from __future__ import annotations

import gzip
import json

from autopsy.core.events import (
    AgentStartEvent,
    EventKind,
    LogEvent,
    Manifest,
)
from autopsy.core.store.local_fs import LocalFilesystemStore


def _ev(kind: EventKind, session_id: str, **extra):
    base = dict(
        event_id="01HXY00000000000000000000" + str(extra.pop("seq", "0")),
        parent_id=None,
        session_id=session_id,
        trace_id=session_id,
        timestamp_ns=1,
        kind=kind,
    )
    if kind is EventKind.AGENT_START:
        return AgentStartEvent(**base, agent_name="a")
    if kind is EventKind.LOG:
        return LogEvent(**base, name="n", attributes=extra.get("attrs", {}))
    raise ValueError(kind)


def _manifest(session_id: str, status="ok", event_count=2) -> Manifest:
    return Manifest(
        session_id=session_id,
        agent_name="a",
        start_time_ns=1,
        end_time_ns=1_000_000,
        duration_ms=1.0,
        status=status,
        error_type=None,
        event_count=event_count,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=2,
        monotonic_ns_at_start=1,
    )


def test_write_events_creates_session_dir_lazily(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000001"
    session_dir = tmp_path / "sessions" / sid
    assert not session_dir.exists()
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    assert session_dir.exists()
    assert (session_dir / "events.jsonl").exists()


def test_events_are_jsonl_one_per_line(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000002"
    store.write_events(sid, [
        _ev(EventKind.AGENT_START, sid, seq="1"),
        _ev(EventKind.LOG, sid, seq="2"),
    ])
    lines = (tmp_path / "sessions" / sid / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)


def test_finalize_seals_manifest_and_gzips_events(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000003"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    sd = tmp_path / "sessions" / sid
    assert (sd / "manifest.json").exists()
    assert (sd / "events.jsonl.gz").exists()
    assert not (sd / "events.jsonl").exists()
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        lines = f.read().splitlines()
    assert len(lines) == 1
    payload = json.loads((sd / "manifest.json").read_text())
    assert payload["status"] == "ok"
    assert payload["autopsy_format_version"] == 1


def test_manifest_written_atomically(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000004"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    sd = tmp_path / "sessions" / sid
    assert not (sd / "manifest.json.tmp").exists()


def test_list_sessions_returns_finalized_only(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    for n in (1, 2):
        sid = f"01HXY00000000000000000000{n}"
        store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
        store.finalize_session(_manifest(sid))
    rows = store.list_sessions()
    assert {r["session_id"] for r in rows} == {
        "01HXY000000000000000000001",
        "01HXY000000000000000000002",
    }


def test_load_session_returns_manifest_and_events(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000005"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    payload = store.load_session(sid)
    assert payload is not None
    assert payload["manifest"]["session_id"] == sid
    assert len(payload["events"]) == 1


def test_load_session_returns_none_for_unknown(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    assert store.load_session("nope") is None


def test_delete_session_removes_dir_and_index_row(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000006"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    store.delete_session(sid)
    assert not (tmp_path / "sessions" / sid).exists()
    assert store.list_sessions() == []


def test_partial_lines_in_events_jsonl_are_skipped_on_load(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000007"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    sd = tmp_path / "sessions" / sid
    with (sd / "events.jsonl").open("a") as f:
        f.write("{not valid json\n")
    store.finalize_session(_manifest(sid, event_count=1))
    payload = store.load_session(sid)
    assert payload is not None
    assert len(payload["events"]) == 1


def test_root_is_created_if_missing(tmp_path):
    root = tmp_path / "does" / "not" / "exist"
    store = LocalFilesystemStore(root=root)
    sid = "01HXY000000000000000000008"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    assert (root / "sessions" / sid / "events.jsonl").exists()
