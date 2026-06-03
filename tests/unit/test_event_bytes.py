"""Unit tests for cheap event byte estimates and merge helpers."""
from __future__ import annotations

from autopsy.core.event_bytes import (
    cap_events_for_evaluation,
    estimated_event_json_bytes,
    merge_events_chronologically,
)
from autopsy.core.events import EventKind, LogEvent


def test_estimated_bytes_within_factor_of_json():
    ev = LogEvent(
        event_id="01HXY00000000000000000001",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=1,
        kind=EventKind.LOG,
        name="hello" + "x" * 80,
    )
    est = estimated_event_json_bytes(ev)
    actual = len(ev.model_dump_json().encode("utf-8"))
    assert est >= actual * 0.5
    assert est <= actual * 2.0


def test_merge_skips_sort_when_ordered():
    events = [
        LogEvent(
            event_id=f"01HXY0000000000000000000{i:02d}",
            parent_id=None,
            session_id="s",
            trace_id="s",
            timestamp_ns=i,
            kind=EventKind.LOG,
            name=str(i),
        )
        for i in range(5)
    ]
    merged = merge_events_chronologically(events)
    assert [e.event_id for e in merged] == [e.event_id for e in events]


def test_cap_events_keeps_tail():
    events = [
        LogEvent(
            event_id=f"01HXY0000000000000000000{i:02d}",
            parent_id=None,
            session_id="s",
            trace_id="s",
            timestamp_ns=i,
            kind=EventKind.LOG,
            name=str(i),
        )
        for i in range(10)
    ]
    capped = cap_events_for_evaluation(events, 3)
    assert len(capped) == 3
    assert [e.timestamp_ns for e in capped] == [7, 8, 9]
