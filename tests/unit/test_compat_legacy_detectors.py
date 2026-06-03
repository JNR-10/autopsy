"""Legacy v0 bundles convert to BaseEvents for detector replay."""
from __future__ import annotations

import json
from pathlib import Path

from autopsy.core.compat import (
    LegacyBundleReader,
    legacy_events_to_base,
    load_session_events_for_detectors,
)
from autopsy.core.events import EventKind, LLMResponseEvent, ToolCallEndEvent
from autopsy.detectors.tool_failure import ToolFailureDetector


def _write_v0_tool_error(tmp_path: Path, session_id: str) -> None:
    payload = {
        "session_id": session_id,
        "created_at": 1.0,
        "agent_name": "a",
        "events": [
            {
                "event_type": "tool_result",
                "node_id": "t1",
                "timestamp": 1.0,
                "tool_name": "search",
                "error": "connection reset",
            },
            {
                "event_type": "llm_response",
                "node_id": "l1",
                "timestamp": 2.0,
                "model": "gpt",
                "content": "ok",
                "finish_reason": "stop",
            },
        ],
        "summary": {"status": "success"},
    }
    p = tmp_path / "sessions" / f"{session_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload))


def test_legacy_events_to_base_tool_failure(tmp_path):
    sid = "01HXY000000000000000000099"
    _write_v0_tool_error(tmp_path, sid)
    events = legacy_events_to_base(
        json.loads((tmp_path / "sessions" / f"{sid}.json").read_text())["events"],
        session_id=sid,
    )
    assert any(isinstance(e, ToolCallEndEvent) for e in events)
    det = ToolFailureDetector()
    v = det.evaluate(events, outcome="ok")
    assert v is not None


def test_load_session_events_v0_via_reader(tmp_path):
    sid = "01HXY000000000000000000099"
    _write_v0_tool_error(tmp_path, sid)
    reader = LegacyBundleReader(root=tmp_path)
    events, outcome = load_session_events_for_detectors(reader, sid)
    assert outcome == "ok"
    assert any(e.kind is EventKind.LLM_RESPONSE for e in events)
    assert isinstance(events[0], (ToolCallEndEvent, LLMResponseEvent))
