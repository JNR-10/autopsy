"""events_for_detectors avoids disk unless detector_full_trace is enabled."""
from __future__ import annotations

from unittest.mock import patch

import autopsy.core.session as session_mod
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, ToolCallStartEvent
from autopsy.core.session import Session


def test_events_for_detectors_skips_disk_without_full_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        detector_full_trace=False,
    )
    s = Session.begin(config=cfg, agent_name="a", sample="all")
    s.record_event(ToolCallStartEvent(
        event_id="01HXY00000000000000000001",
        parent_id=None,
        session_id=s.session_id,
        trace_id=s.session_id,
        timestamp_ns=1,
        kind=EventKind.TOOL_CALL_START,
        tool_name="t",
        tool_args={},
    ))
    session_dir = tmp_path / "sessions" / s.session_id
    session_dir.mkdir(parents=True)
    (session_dir / "events.jsonl").write_text("{}\n")

    with patch(
        "autopsy.core.compat.load_v1_base_events",
    ) as load_disk:
        events = s.events_for_detectors()
        load_disk.assert_not_called()

    assert len(events) == 1
