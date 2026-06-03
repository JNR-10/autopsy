"""Writer keeps sessions on warn verdicts when promote_on_warn is set."""
from __future__ import annotations

import time

from autopsy.core.config import LensConfig
from autopsy.core.events import DetectorVerdictEvent, EventKind
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def test_verdict_warn_promotes_kept_when_configured(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors", promote_on_warn=True)
    store = __import__(
        "autopsy.core.store.local_fs", fromlist=["LocalFilesystemStore"]
    ).LocalFilesystemStore(root=tmp_path)
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        w.enqueue(DetectorVerdictEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=1, kind=EventKind.DETECTOR_VERDICT,
            detector_name="high_latency", verdict="warn", reason="slow",
        ))
        w.end_session(SID, outcome="ok", error_type="detector_warn:high_latency")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / SID / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)
    assert (tmp_path / "sessions" / SID / "manifest.json").exists()
