"""Tests for writer kept promotion on detector_verdict events."""
from __future__ import annotations

import time

from autopsy.core.config import LensConfig
from autopsy.core.events import DetectorVerdictEvent, EventKind
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def test_verdict_fail_promotes_kept(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    w = Writer(config=cfg, store=__import__(
        "autopsy.core.store.local_fs", fromlist=["LocalFilesystemStore"]
    ).LocalFilesystemStore(root=tmp_path))
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        w.enqueue(DetectorVerdictEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=1, kind=EventKind.DETECTOR_VERDICT,
            detector_name="tool_loop", verdict="fail", reason="loop",
        ))
        w.end_session(SID, outcome="error", error_type="detector:tool_loop")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / SID / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)
    assert (tmp_path / "sessions" / SID / "events.jsonl").exists() or (
        tmp_path / "sessions" / SID / "events.jsonl.gz"
    ).exists()
