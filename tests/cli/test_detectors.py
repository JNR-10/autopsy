"""CLI: autopsy detectors list and rerun."""
from __future__ import annotations

import json

from click.testing import CliRunner

from autopsy.cli.main import cli


def test_detectors_list_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["detectors", "--list", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    names = {r["name"] for r in rows}
    assert "empty_response" in names
    assert "high_latency" in names


def test_detectors_rerun_v1_session(tmp_path, monkeypatch):
    from autopsy.core.config import LensConfig
    from autopsy.core.events import EventKind, ToolCallEndEvent
    from autopsy.core.store.local_fs import LocalFilesystemStore
    from autopsy.core.writer import SampleMode, Writer

    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    store = LocalFilesystemStore(root=tmp_path)
    w = Writer(config=cfg, store=store)
    sid = "01HXY000000000000000000042"
    w.start()
    try:
        w.declare_session(sid, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(ToolCallEndEvent(
            event_id="01HXY00000000000000000000B",
            parent_id=None, session_id=sid, trace_id=sid,
            timestamp_ns=2, kind=EventKind.TOOL_CALL_END,
            tool_name="t", error="boom",
        ))
        w.end_session(sid, outcome="ok")
        import time
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / sid / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)

    runner = CliRunner()
    result = runner.invoke(cli, ["detectors", sid, "--json"])
    assert result.exit_code == 0
    verdicts = json.loads(result.output)
    assert any(v["detector_name"] == "tool_failure" for v in verdicts)
