"""LocalFilesystemStore — the only TraceStore implementation that ships in v1.

Layout (matches the design spec):

    <root>/
      sessions/
        <session_id>/
          manifest.json
          events.jsonl   (gzipped to events.jsonl.gz at finalize)
          artifacts/<sha256>.bin
      index.sqlite

Invariants:
- write_events() appends newline-delimited JSON. It never fsyncs. The
  session directory is created lazily on first call.
- finalize_session() writes the manifest atomically (write tmp + rename),
  fsyncs the events file, gzips it in place, and inserts the index row.
- The events file is parsed line-by-line with malformed lines skipped
  (host SIGKILL may leave a partial trailing line — that's acceptable).
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from ..events_v2 import BaseEvent, Manifest
from .sqlite_index import SQLiteIndex

logger = logging.getLogger("autopsy.store")


class LocalFilesystemStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "sessions").mkdir(parents=True, exist_ok=True)
        self.index = SQLiteIndex(self.root / "index.sqlite")

    def _session_dir(self, session_id: str) -> Path:
        return self.root / "sessions" / session_id

    def write_events(self, session_id: str, events: Iterable[BaseEvent]) -> None:
        sd = self._session_dir(session_id)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "artifacts").mkdir(exist_ok=True)
        path = sd / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for ev in events:
                f.write(ev.model_dump_json())
                f.write("\n")

    def finalize_session(self, manifest: Manifest) -> None:
        sd = self._session_dir(manifest.session_id)
        sd.mkdir(parents=True, exist_ok=True)

        events_path = sd / "events.jsonl"
        if not events_path.exists():
            events_path.write_text("")
        if events_path.exists():
            with events_path.open("rb") as src:
                src.flush()
                try:
                    os.fsync(src.fileno())
                except OSError:
                    pass
            gz_path = sd / "events.jsonl.gz"
            with events_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            events_path.unlink()

        manifest_path = sd / "manifest.json"
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(manifest.model_dump_json(indent=2))
        os.replace(tmp, manifest_path)

        self.index.upsert(manifest, str(sd))

    def list_sessions(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.index.list(limit=limit)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        sd = self._session_dir(session_id)
        manifest_path = sd / "manifest.json"
        if not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text())
        events: list[dict[str, Any]] = []
        gz = sd / "events.jsonl.gz"
        plain = sd / "events.jsonl"
        opener = (lambda: gzip.open(gz, "rt", encoding="utf-8")) if gz.exists() else (
            (lambda: plain.open("r", encoding="utf-8")) if plain.exists() else None
        )
        if opener is not None:
            with opener() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("autopsy: skipping malformed event in %s", sd)
                        continue
        return {"manifest": manifest, "events": events}

    def delete_session(self, session_id: str) -> None:
        sd = self._session_dir(session_id)
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        self.index.delete(session_id)

    def reindex(self) -> int:
        self.index.clear()
        count = 0
        sessions_root = self.root / "sessions"
        if not sessions_root.exists():
            return 0
        for sd in sessions_root.iterdir():
            if not sd.is_dir():
                continue
            manifest_path = sd / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                m = Manifest.model_validate_json(manifest_path.read_text())
            except Exception:
                logger.warning("autopsy: bad manifest at %s, marking partial", sd)
                continue
            if m.status == "live":
                m = m.model_copy(update={"status": "partial"})
                manifest_path.write_text(m.model_dump_json(indent=2))
            self.index.upsert(m, str(sd))
            count += 1
        return count

    def _session_disk_bytes(self, session_dir) -> int:
        total = 0
        for p in session_dir.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
        return total

    def evict(
        self,
        *,
        max_total_disk_mb: int,
        max_session_age_days: int,
        now_ns: int,
    ) -> list[dict]:
        """Apply age + size eviction. Returns the rows that were deleted.

        Age first: sessions older than max_session_age_days are removed
        regardless of size (skipping pinned). Then, if total bytes still
        exceeds max_total_disk_mb, remove oldest non-pinned sessions
        until under the cap.
        """
        removed: list[dict] = []
        max_age_ns = max_session_age_days * 86_400 * 1_000_000_000
        for row in self.index.find_evictable(max_age_ns=max_age_ns, now_ns=now_ns):
            self.delete_session(row["session_id"])
            removed.append(row)

        cap_bytes = max_total_disk_mb * 1024 * 1024
        sessions_root = self.root / "sessions"
        if not sessions_root.exists():
            return removed

        def total_bytes() -> int:
            total = 0
            for sd in sessions_root.iterdir():
                if sd.is_dir():
                    total += self._session_disk_bytes(sd)
            return total

        current = total_bytes()
        if current <= cap_bytes:
            return removed
        for row in self.index.find_evictable(max_age_ns=None, now_ns=now_ns):
            if current <= cap_bytes:
                break
            sd = sessions_root / row["session_id"]
            size = self._session_disk_bytes(sd) if sd.exists() else 0
            self.delete_session(row["session_id"])
            removed.append(row)
            current -= size
        return removed
