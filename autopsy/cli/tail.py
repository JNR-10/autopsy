"""Tail command logic: last N events for finalized sessions, poll for live."""
from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path
from typing import TextIO

from autopsy.core.compat import LegacyBundleReader


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


def _events_file(session_dir: Path) -> Path | None:
    plain = session_dir / "events.jsonl"
    if plain.exists():
        return plain
    gz = session_dir / "events.jsonl.gz"
    if gz.exists():
        return gz
    return None


def _open_events(path: Path):
    if path.suffix == ".gz" or path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _read_all_lines(path: Path) -> list[str]:
    with _open_events(path) as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def _emit_line(line: str, *, as_json: bool, out: TextIO) -> None:
    if as_json:
        try:
            obj = json.loads(line)
            out.write(json.dumps(obj, separators=(",", ":"), sort_keys=True))
        except json.JSONDecodeError:
            out.write(json.dumps({"raw": line}, separators=(",", ":")))
        out.write("\n")
    else:
        try:
            ev = json.loads(line)
            kind = ev.get("kind") or ev.get("event_type", "?")
            out.write(f"{kind}\n")
        except json.JSONDecodeError:
            out.write(f"{line}\n")
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
    events_path = _events_file(session_dir)

    if status != "live":
        if events_path is None:
            return
        all_lines = _read_all_lines(events_path)
        for line in all_lines[-lines:]:
            _emit_line(line, as_json=as_json, out=sink)
        return

    if events_path is None:
        events_path = session_dir / "events.jsonl"

    seen = 0
    polls = 0
    while True:
        if events_path.exists():
            with events_path.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue
                    if i >= seen:
                        _emit_line(line, as_json=as_json, out=sink)
                        seen = i + 1

        current_status = _manifest_status(session_dir)
        if current_status is not None and current_status != "live":
            break

        polls += 1
        if max_polls is not None and polls >= max_polls:
            break

        time.sleep(poll_interval_s)
