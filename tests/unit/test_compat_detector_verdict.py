from autopsy.core.compat import _v1_event_to_legacy


def test_fail_verdict_maps_to_node_error():
    legacy = _v1_event_to_legacy({
        "kind": "detector_verdict",
        "event_id": "e1",
        "session_id": "s",
        "detector_name": "tool_loop",
        "verdict": "fail",
        "reason": "loop",
        "timestamp_ns": 1_000_000_000,
    })
    assert legacy["event_type"] == "node_error"
    assert legacy["error_type"] == "detector:tool_loop"
    assert legacy["error_message"] == "loop"


def test_pass_verdict_omitted():
    assert _v1_event_to_legacy({
        "kind": "detector_verdict", "verdict": "pass",
        "detector_name": "x", "timestamp_ns": 1,
    }) is None
