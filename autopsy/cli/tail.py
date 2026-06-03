"""Tail command logic: last N events for finalized sessions, poll for live."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from autopsy.core.compat import LegacyBundleReader
from autopsy.core.event_codec import load_session_event_dicts


def _session_dir(reader: LegacyBundleReader, session_id: str) -> Path:
    return reader.root / "sessions" / session_id


def _manifest_status(session_dir: Path) -> str | None:
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
        return manifest.get("status")
    except Exception:
        return None


def _emit_event(ev: dict[str, Any], *, as_json: bool, out: TextIO) -> None:
    if as_json:
        out.write(json.dumps(ev, separators=(",", ":"), sort_keys=True))
        out.write("\n")
    else:
        kind = ev.get("kind") or ev.get("event_type", "?")
        out.write(f"{kind}\n")
    out.flush()


def tail_session(
    reader: LegacyBundleReader,
    session_id: str,
    *,
    lines: int = 20,
    as_json: bool = False,
    poll_interval_s: float = 0.5,
    max_polls: int | None = None,
    out: TextIO | None = None,
) -> None:
    """Print last N events (finalized) or poll new events (live session)."""
    sink = out or sys.stdout
    session_dir = _session_dir(reader, session_id)
    if not session_dir.exists():
        raise FileNotFoundError(f"session directory not found: {session_id}")

    status = _manifest_status(session_dir)

    if status != "live":
        events = load_session_event_dicts(session_dir)
        for ev in events[-lines:]:
            _emit_event(ev, as_json=as_json, out=sink)
        return

    seen = 0
    polls = 0
    while True:
        events = load_session_event_dicts(session_dir)
        for ev in events[seen:]:
            _emit_event(ev, as_json=as_json, out=sink)
        seen = len(events)

        current_status = _manifest_status(session_dir)
        if current_status is not None and current_status != "live":
            break

        polls += 1
        if max_polls is not None and polls >= max_polls:
            break
        time.sleep(poll_interval_s)
