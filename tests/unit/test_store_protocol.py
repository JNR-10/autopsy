"""Protocol shape test for TraceStore."""
from __future__ import annotations

import inspect

from autopsy.core.store import TraceStore


def test_protocol_has_expected_methods():
    expected = {"write_events", "finalize_session", "list_sessions",
                "load_session", "delete_session", "reindex"}
    members = {name for name, _ in inspect.getmembers(TraceStore) if not name.startswith("_")}
    missing = expected - members
    assert not missing, f"TraceStore is missing methods: {missing}"
