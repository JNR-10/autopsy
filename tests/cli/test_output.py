"""Smoke tests for autopsy.cli.output JSON helpers."""
from __future__ import annotations

import json

from autopsy.cli.output import session_list_json, session_summary_json


def test_session_list_json_round_trip():
    rows = [
        {"session_id": "abc", "agent_name": "agent", "summary": {"status": "success"}},
    ]
    parsed = json.loads(session_list_json(rows))
    assert parsed == rows


def test_session_summary_json_round_trip():
    bundle = {
        "session_id": "abc",
        "agent_name": "agent",
        "summary": {
            "status": "success",
            "error_count": 0,
            "total_tokens": 10,
            "node_count": 2,
            "total_duration_ms": 5,
        },
        "events": [],
    }
    parsed = json.loads(session_summary_json(bundle))
    assert parsed["session_id"] == "abc"
    assert parsed["status"] == "success"
    assert parsed["detector_verdicts"] == []
    assert parsed["errors"] == []


def test_session_list_json_empty():
    assert json.loads(session_list_json([])) == []
