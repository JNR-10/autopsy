"""Cheap event size estimates and merge helpers (buffer caps, detector input)."""
from __future__ import annotations

from typing import Any, Iterable

from .events import BaseEvent


def estimated_event_json_bytes(ev: BaseEvent) -> int:
    """Approximate UTF-8 JSONL line size without serializing to JSON."""
    try:
        payload = ev.model_dump(mode="python")
    except Exception:
        return 256

    total = 96

    def walk(value: Any) -> None:
        nonlocal total
        if value is None:
            total += 4
        elif isinstance(value, bool):
            total += 5
        elif isinstance(value, (int, float)):
            total += 16
        elif isinstance(value, str):
            total += len(value.encode("utf-8", errors="replace")) + 3
        elif isinstance(value, dict):
            total += 2
            for key, item in value.items():
                total += len(str(key)) + 3
                walk(item)
        elif isinstance(value, (list, tuple)):
            total += 2
            for item in value:
                walk(item)
        else:
            total += 32

    walk(payload)
    return total


def merge_events_chronologically(events: Iterable[BaseEvent]) -> list[BaseEvent]:
    """Return events sorted by timestamp_ns; skip sort when already ordered."""
    items = list(events)
    if len(items) <= 1:
        return items
    ordered = True
    prev = items[0].timestamp_ns
    for ev in items[1:]:
        ts = ev.timestamp_ns
        if ts < prev:
            ordered = False
            break
        prev = ts
    if ordered:
        return items
    return sorted(items, key=lambda e: e.timestamp_ns)


def cap_events_for_evaluation(
    events: list[BaseEvent], limit: int,
) -> list[BaseEvent]:
    """Keep the most recent events when over the detector evaluation cap."""
    if limit <= 0 or len(events) <= limit:
        return events
    return merge_events_chronologically(events)[-limit:]
