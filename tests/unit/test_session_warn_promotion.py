"""Warn-tier detectors must persist sessions when promote_on_warn is enabled."""
from __future__ import annotations

import json
import time

import autopsy.core.session as session_mod
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LLMResponseEvent
from autopsy.core.session import Session, get_writer


def test_warn_only_promotes_session_with_promote_on_warn(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        enabled_detectors=["high_latency"],
        promote_on_warn=True,
        latency_threshold_ms=1,
    )
    s = Session.begin(config=cfg, agent_name="a", sample="errors")
    s.record_event(LLMResponseEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None,
        session_id=s.session_id,
        trace_id=s.session_id,
        timestamp_ns=1,
        kind=EventKind.LLM_RESPONSE,
        model="m",
        latency_ms=5000.0,
    ))
    s.end(outcome="ok")
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)

    manifest_path = tmp_path / "sessions" / s.session_id / "manifest.json"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if manifest_path.exists():
            break
        time.sleep(0.02)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["error_type"] == "detector_warn:high_latency"
