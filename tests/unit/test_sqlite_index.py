"""Unit tests for the SQLite derived index."""
from __future__ import annotations

from autopsy.core.events_v2 import Manifest
from autopsy.core.store.sqlite_index import SQLiteIndex


def _manifest(sid, *, start_ns=1000, status="ok", event_count=3) -> Manifest:
    return Manifest(
        session_id=sid,
        agent_name="a",
        start_time_ns=start_ns,
        end_time_ns=start_ns + 1_000_000,
        duration_ms=1.0,
        status=status,
        error_type=None,
        event_count=event_count,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=start_ns,
        monotonic_ns_at_start=start_ns,
    )


def test_index_creates_schema(tmp_path):
    SQLiteIndex(tmp_path / "i.sqlite")
    assert (tmp_path / "i.sqlite").exists()


def test_upsert_then_list(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("01HXY000000000000000000001"), "/p/1")
    rows = idx.list()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "01HXY000000000000000000001"
    assert rows[0]["status"] == "ok"
    assert rows[0]["path"] == "/p/1"


def test_list_orders_newest_first(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("a", start_ns=100), "/p/a")
    idx.upsert(_manifest("b", start_ns=200), "/p/b")
    rows = idx.list()
    assert [r["session_id"] for r in rows] == ["b", "a"]


def test_list_limit(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    for i in range(5):
        idx.upsert(_manifest(f"s{i}", start_ns=i * 100), f"/p/{i}")
    assert len(idx.list(limit=2)) == 2


def test_upsert_overwrites_same_session_id(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("s", status="live"), "/p")
    idx.upsert(_manifest("s", status="ok"), "/p")
    rows = idx.list()
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"


def test_delete(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("s"), "/p")
    idx.delete("s")
    assert idx.list() == []


def test_pinned_sessions_are_returned(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    m = _manifest("s").model_copy(update={"pinned": True})
    idx.upsert(m, "/p")
    rows = idx.list()
    assert rows[0]["pinned"] == 1


def test_clear_empties_table(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("a"), "/p/a")
    idx.upsert(_manifest("b"), "/p/b")
    idx.clear()
    assert idx.list() == []


def test_wal_mode_enabled(tmp_path):
    SQLiteIndex(tmp_path / "i.sqlite")
    import sqlite3
    with sqlite3.connect(tmp_path / "i.sqlite") as c:
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
