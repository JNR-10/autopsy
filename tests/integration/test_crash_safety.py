"""Crash safety: kill -9 mid-session leaves recoverable trace files."""
from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
import time

from autopsy.core.events import Manifest
from autopsy.core.store.local_fs import LocalFilesystemStore


def test_sigkill_mid_session_leaves_recoverable_files(tmp_path):
    script = tmp_path / "run.py"
    script.write_text(textwrap.dedent(f"""
        import os, time
        os.environ["AUTOPSY_SESSION_DIR"] = {str(tmp_path)!r}
        os.environ["AUTOPSY_SAMPLE"] = "all"
        from autopsy import lens

        @lens.trace
        def slow():
            for _ in range(1000):
                time.sleep(0.01)

        slow()
    """).strip())

    proc = subprocess.Popen([sys.executable, str(script)])
    time.sleep(1.0)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=2.0)

    sessions = tmp_path / "sessions"
    assert sessions.exists()
    dirs = [d for d in sessions.iterdir() if d.is_dir()]
    assert dirs, "no session directory created"
    sd = dirs[0]
    events_path = sd / "events.jsonl"
    assert events_path.exists() or (sd / "events.jsonl.gz").exists()


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
