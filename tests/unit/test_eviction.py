"""Tests for the size + age eviction policy on LocalFilesystemStore."""
from __future__ import annotations

import time

from autopsy.core.events_v2 import AgentStartEvent, EventKind, Manifest
from autopsy.core.store.local_fs import LocalFilesystemStore


def _ev(sid: str) -> AgentStartEvent:
    return AgentStartEvent(
        event_id="01HXY00000000000000000000" + sid[-1],
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=1,
        kind=EventKind.AGENT_START,
        agent_name="a",
    )


def _manifest(sid: str, *, start_ns: int, pinned=False) -> Manifest:
    return Manifest(
        session_id=sid,
        agent_name="a",
        start_time_ns=start_ns,
        end_time_ns=start_ns + 1,
        duration_ms=1.0,
        status="ok",
        error_type=None,
        event_count=1,
        dropped_events=0,
        pinned=pinned,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=start_ns,
        monotonic_ns_at_start=start_ns,
    )


def _make_session(store, sid, *, start_ns, pinned=False, padding_kb=0):
    store.write_events(sid, [_ev(sid)])
    if padding_kb:
        sd = store.root / "sessions" / sid
        (sd / "artifacts" / "pad.bin").write_bytes(b"x" * padding_kb * 1024)
    store.finalize_session(_manifest(sid, start_ns=start_ns, pinned=pinned))


def test_evict_by_age_removes_old_unpinned(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    one_day_ns = 86_400 * 1_000_000_000
    _make_session(store, "01HXY000000000000000000001", start_ns=now_ns - 40 * one_day_ns)
    _make_session(store, "01HXY000000000000000000002", start_ns=now_ns)
    removed = store.evict(max_total_disk_mb=10_000, max_session_age_days=30, now_ns=now_ns)
    ids = {r["session_id"] for r in removed}
    assert ids == {"01HXY000000000000000000001"}
    assert {r["session_id"] for r in store.list_sessions()} == {"01HXY000000000000000000002"}


def test_evict_by_age_respects_pinned(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    one_day_ns = 86_400 * 1_000_000_000
    _make_session(
        store, "01HXY000000000000000000001",
        start_ns=now_ns - 40 * one_day_ns, pinned=True,
    )
    removed = store.evict(max_total_disk_mb=10_000, max_session_age_days=30, now_ns=now_ns)
    assert removed == []


def test_evict_by_size_removes_oldest_first(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    _make_session(store, "01HXY000000000000000000001", start_ns=now_ns - 3000, padding_kb=600)
    _make_session(store, "01HXY000000000000000000002", start_ns=now_ns - 2000, padding_kb=600)
    _make_session(store, "01HXY000000000000000000003", start_ns=now_ns - 1000, padding_kb=600)
    removed = store.evict(max_total_disk_mb=1, max_session_age_days=365 * 10, now_ns=now_ns)
    removed_ids = [r["session_id"] for r in removed]
    assert removed_ids and removed_ids[0] == "01HXY000000000000000000001"
    remaining = {r["session_id"] for r in store.list_sessions()}
    assert "01HXY000000000000000000003" in remaining


def test_evict_by_size_skips_pinned(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    _make_session(
        store, "01HXY000000000000000000001",
        start_ns=now_ns - 3000, padding_kb=600, pinned=True,
    )
    _make_session(store, "01HXY000000000000000000002", start_ns=now_ns - 2000, padding_kb=600)
    removed = store.evict(max_total_disk_mb=1, max_session_age_days=365 * 10, now_ns=now_ns)
    assert "01HXY000000000000000000001" not in {r["session_id"] for r in removed}
