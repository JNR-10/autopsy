"""Crash safety: kill -9 mid-session leaves recoverable trace files."""
from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from autopsy.core.events import Manifest
from autopsy.core.store.local_fs import LocalFilesystemStore


def _session_has_spilled_events(session_dir: Path) -> bool:
    for name in ("events.jsonl", "events.msgpack", "events.jsonl.gz", "events.msgpack.gz"):
        if (session_dir / name).exists():
            return True
    return False


@pytest.mark.slow
def test_sigkill_mid_session_leaves_recoverable_files(tmp_path):
    """After SIGKILL, at least one spilled events file must exist on disk.

    Writer batching means the session directory appears only after the first
    spill, not at declare_session — the child must emit enough events first.
    """
    script = tmp_path / "run.py"
    script.write_text(textwrap.dedent(f"""
        import os, time
        os.environ["AUTOPSY_SESSION_DIR"] = {str(tmp_path)!r}
        os.environ["AUTOPSY_SAMPLE"] = "all"
        os.environ["AUTOPSY_WRITER_SPILL_BATCH_EVENTS"] = "8"
        from autopsy import lens, log

        @lens.trace
        def slow():
            for i in range(200):
                log("step", index=i)
                time.sleep(0.01)

        slow()
    """).strip())

    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stderr=subprocess.PIPE,
        cwd=str(tmp_path.parent),
    )
    sessions = tmp_path / "sessions"
    session_dir: Path | None = None
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if sessions.exists():
            for d in sessions.iterdir():
                if d.is_dir() and _session_has_spilled_events(d):
                    session_dir = d
                    break
        if session_dir is not None:
            break
        time.sleep(0.05)
    assert session_dir is not None, (
        "no spilled events on disk before SIGKILL "
        f"(stderr={proc.stderr.read().decode()[:500]!r})"
    )
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=2.0)

    assert _session_has_spilled_events(session_dir)


def test_reindex_marks_unfinalized_session_partial(tmp_path):
    sid = "01HXY000000000000000000099"
    sd = tmp_path / "sessions" / sid
    sd.mkdir(parents=True)
    (sd / "artifacts").mkdir()
    (sd / "events.jsonl").write_text('{"kind":"agent_start"}\n')
    live_manifest = Manifest(
        session_id=sid, agent_name="a", start_time_ns=1,
        end_time_ns=None, duration_ms=None, status="live",
        error_type=None, event_count=1, dropped_events=0,
        autopsy_format_version=1, autopsy_version="0.2.0",
        wall_clock_ns_at_start=1, monotonic_ns_at_start=1,
    )
    (sd / "manifest.json").write_text(live_manifest.model_dump_json())

    store = LocalFilesystemStore(root=tmp_path)
    n = store.reindex()
    assert n == 1
    rows = store.list_sessions()
    assert rows[0]["status"] == "partial"
