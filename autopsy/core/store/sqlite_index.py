"""SQLite-backed derived index for fast session listing.

The index is *derived* — the source of truth is always the per-session
manifest.json on disk. If this file is missing or corrupted, the
`LocalFilesystemStore.reindex()` method rebuilds it by walking the
sessions directory.

WAL mode is enabled so the dashboard / CLI can read concurrently while
the writer thread inserts. Writes use a short-held connection opened per
operation; we never hold the connection across calls.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..events_v2 import Manifest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  start_time_ns INTEGER NOT NULL,
  end_time_ns INTEGER,
  duration_ms INTEGER,
  status TEXT NOT NULL,
  error_type TEXT,
  event_count INTEGER,
  dropped_events INTEGER DEFAULT 0,
  pinned INTEGER DEFAULT 0,
  path TEXT NOT NULL,
  schema_version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON sessions(start_time_ns DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
"""


class SQLiteIndex:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def upsert(self, manifest: Manifest, path: str) -> None:
        with self._connect() as c:
            c.execute(
                """INSERT INTO sessions (
                       session_id, agent_name, start_time_ns, end_time_ns,
                       duration_ms, status, error_type, event_count,
                       dropped_events, pinned, path, schema_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       agent_name=excluded.agent_name,
                       start_time_ns=excluded.start_time_ns,
                       end_time_ns=excluded.end_time_ns,
                       duration_ms=excluded.duration_ms,
                       status=excluded.status,
                       error_type=excluded.error_type,
                       event_count=excluded.event_count,
                       dropped_events=excluded.dropped_events,
                       pinned=excluded.pinned,
                       path=excluded.path,
                       schema_version=excluded.schema_version
                """,
                (
                    manifest.session_id,
                    manifest.agent_name,
                    manifest.start_time_ns,
                    manifest.end_time_ns,
                    int(manifest.duration_ms) if manifest.duration_ms is not None else None,
                    manifest.status,
                    manifest.error_type,
                    manifest.event_count,
                    manifest.dropped_events,
                    1 if manifest.pinned else 0,
                    path,
                    manifest.autopsy_format_version,
                ),
            )

    def delete(self, session_id: str) -> None:
        with self._connect() as c:
            c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def list(self, limit: int | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM sessions ORDER BY start_time_ns DESC"
        params: tuple = ()
        if limit is not None:
            q += " LIMIT ?"
            params = (limit,)
        with self._connect() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> None:
        with self._connect() as c:
            c.execute("DELETE FROM sessions")

    def find_evictable(self, *, max_age_ns: int | None, now_ns: int) -> list[dict[str, Any]]:
        """Return non-pinned sessions older than max_age_ns (oldest first)."""
        with self._connect() as c:
            if max_age_ns is None:
                rows = c.execute(
                    "SELECT * FROM sessions WHERE pinned = 0 ORDER BY start_time_ns ASC"
                ).fetchall()
            else:
                cutoff = now_ns - max_age_ns
                rows = c.execute(
                    "SELECT * FROM sessions WHERE pinned = 0 AND start_time_ns < ? "
                    "ORDER BY start_time_ns ASC",
                    (cutoff,),
                ).fetchall()
        return [dict(r) for r in rows]
