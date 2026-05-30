"""TraceStore Protocol — the seam for swappable storage backends.

`LocalFilesystemStore` is the only implementation that ships in v1. The
Protocol exists so S3 / GCS / other backends can slot in later without
touching the writer.

All methods are synchronous. The writer thread is the only caller; the
writer is what isolates the hot path from disk I/O.
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable

from ..events_v2 import BaseEvent, Manifest
from .local_fs import LocalFilesystemStore

__all__ = ["LocalFilesystemStore", "TraceStore"]


@runtime_checkable
class TraceStore(Protocol):
    """Backend-agnostic API for persisting and reading sessions."""

    def write_events(self, session_id: str, events: Iterable[BaseEvent]) -> None:
        """Append events to the session's events log. Creates the session
        directory lazily on first call. Never blocks longer than a local
        write; never fsyncs per call."""
        ...

    def finalize_session(self, manifest: Manifest) -> None:
        """Seal the session: write final manifest atomically, fsync the
        events file, gzip the events log, insert into the index."""
        ...

    def list_sessions(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return session summary rows (newest first)."""
        ...

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Return the full session payload (manifest + events) or None."""
        ...

    def delete_session(self, session_id: str) -> None:
        """Delete the session directory and its index row in one transaction."""
        ...

    def reindex(self) -> int:
        """Rebuild the index by walking the sessions directory.

        Returns the number of sessions reindexed.
        """
        ...
