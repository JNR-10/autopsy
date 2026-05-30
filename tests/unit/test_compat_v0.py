"""Tests for reading legacy (implicit v0) sessions into the TraceBundle shape."""
from __future__ import annotations

import json
from pathlib import Path

from autopsy.core.compat import read_v0_bundle


def _write_v0(tmp_path: Path, session_id: str) -> Path:
    payload = {
        "session_id": session_id,
        "created_at": 1700000000.0,
        "agent_name": "old_agent",
        "input_query": "do thing",
        "agent_module_path": "/x/y.py",
        "agent_fn_name": "x.y",
        "events": [
            {"event_type": "session_start", "session_id": session_id,
             "timestamp": 1.0, "agent_name": "old_agent"},
            {"event_type": "node_start", "node_id": "n1", "node_type": "agent",
             "node_name": "root", "parent_node_id": None, "depth": 0},
            {"event_type": "node_end", "node_id": "n1", "duration_ms": 10.0,
             "output_data": "done"},
        ],
        "dag_edges": [],
        "node_index": {},
        "replay_checkpoints": {},
        "summary": {"status": "success", "error_count": 0},
    }
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    p = sessions / f"{session_id}.json"
    p.write_text(json.dumps(payload))
    return p


def test_reads_v0_into_trace_bundle_shape(tmp_path):
    p = _write_v0(tmp_path, "old-1")
    bundle = read_v0_bundle(p)
    assert bundle["session_id"] == "old-1"
    assert bundle["agent_name"] == "old_agent"
    assert len(bundle["events"]) == 3
    assert bundle["events"][0]["event_type"] == "session_start"


def test_v0_reader_returns_none_for_missing_file(tmp_path):
    assert read_v0_bundle(tmp_path / "nope.json") is None


def test_v0_reader_returns_none_for_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert read_v0_bundle(p) is None
