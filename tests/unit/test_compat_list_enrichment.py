"""Tests for LegacyBundleReader list enrichment."""
from __future__ import annotations

import json

from autopsy.core.compat import LegacyBundleReader


def test_list_v1_includes_error_type_and_counts(tmp_path):
    sid = "01HXY000000000000000000099"
    sd = tmp_path / "sessions" / sid
    sd.mkdir(parents=True)
    manifest = {
        "session_id": sid,
        "agent_name": "detector-agent",
        "start_time_ns": 1_000_000_000,
        "status": "error",
        "error_type": "detector:tool_loop",
        "event_count": 42,
        "autopsy_format_version": 1,
        "autopsy_version": "0.2.0",
        "wall_clock_ns_at_start": 1,
        "monotonic_ns_at_start": 1,
    }
    (sd / "manifest.json").write_text(json.dumps(manifest))

    rows = LegacyBundleReader(root=tmp_path).list()
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == sid
    assert row["error_type"] == "detector:tool_loop"
    assert row["node_count"] == 42
    assert row["error_count"] == 1
    assert row["status"] == "error"
