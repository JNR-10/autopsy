"""Writer batches disk spills instead of flushing after every kept event."""
from __future__ import annotations

import time

from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def _log(sid: str, seq: int) -> LogEvent:
    return LogEvent(
        event_id=f"01HXY0000000000000{seq:06d}",
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=seq,
        kind=EventKind.LOG,
        name="n",
    )


class _CountingStore:
    def __init__(self, inner: LocalFilesystemStore) -> None:
        self._inner = inner
        self.write_calls = 0
        self.events_written = 0
        self.finalize_calls = 0

    def write_events(self, session_id: str, events) -> None:
        batch = list(events)
        self.write_calls += 1
        self.events_written += len(batch)
        self._inner.write_events(session_id, batch)

    def finalize_session(self, manifest) -> None:
        self.finalize_calls += 1
        self._inner.finalize_session(manifest)


def test_writer_spills_in_batches_not_per_event(tmp_path):
    inner = LocalFilesystemStore(root=tmp_path)
    counting = _CountingStore(inner)
    sid = "01HXY000000000000000000001"
    cfg = LensConfig(
        session_dir=str(tmp_path),
        writer_spill_batch_events=64,
        writer_spill_interval_ms=0,
    )
    w = Writer(config=cfg, store=counting)
    w.start()
    try:
        w.declare_session(
            sid,
            sample=SampleMode.ALL,
            agent_name="a",
            start_ns=1,
        )
        for i in range(150):
            w.enqueue(_log(sid, i))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and w.drained_count_for_test(sid) < 150:
            time.sleep(0.01)
        w.end_session(sid, outcome="ok")
        w.flush_now()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and counting.finalize_calls < 1:
            time.sleep(0.01)
    finally:
        w.shutdown(timeout=2.0)

    assert counting.events_written == 150
    assert counting.write_calls < 10, (
        f"expected batched spills, got {counting.write_calls} write_events calls"
    )
    assert counting.write_calls >= 2
    assert counting.finalize_calls == 1


def test_sqlite_upsert_only_on_finalize(tmp_path, monkeypatch):
    from autopsy.core.events import AgentStartEvent, Manifest
    from autopsy.core.store import local_fs as local_fs_mod

    upsert_calls: list[str] = []
    original_upsert = local_fs_mod.SQLiteIndex.upsert

    def tracking_upsert(self, manifest, path: str) -> None:
        upsert_calls.append(manifest.session_id)
        return original_upsert(self, manifest, path)

    monkeypatch.setattr(local_fs_mod.SQLiteIndex, "upsert", tracking_upsert)

    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000002"
    store.write_events(sid, [
        AgentStartEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None,
            session_id=sid,
            trace_id=sid,
            timestamp_ns=1,
            kind=EventKind.AGENT_START,
            agent_name="a",
        ),
    ])
    assert upsert_calls == []

    store.finalize_session(Manifest(
        session_id=sid,
        agent_name="a",
        start_time_ns=1,
        end_time_ns=2,
        duration_ms=1.0,
        status="ok",
        event_count=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=1,
        monotonic_ns_at_start=1,
    ))
    assert upsert_calls == [sid]
