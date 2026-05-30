"""Tests for heuristic diagnosis provider."""
from __future__ import annotations

import pytest

from autopsy.diagnostics.heuristic import HeuristicProvider, diagnose_heuristic


@pytest.fixture
def json_error_bundle():
    return {
        "events": [
            {
                "event_type": "node_error",
                "node_id": "n1",
                "error_type": "JSONDecodeError",
                "error_message": "Expecting value: line 1 column 1",
            }
        ],
        "node_index": {
            "n1": {
                "start_event": {"node_name": "summarizer"},
                "error_event": {
                    "error_type": "JSONDecodeError",
                    "error_message": "Expecting value",
                },
            }
        },
    }


def test_diagnose_heuristic_bad_json(json_error_bundle):
    result = diagnose_heuristic(json_error_bundle, "n1")
    assert result.error_category == "bad_json"
    assert "summarizer" in result.root_cause
    assert result.confidence == 0.6


@pytest.mark.asyncio
async def test_heuristic_provider(json_error_bundle):
    provider = HeuristicProvider()
    assert provider.name == "heuristic"
    result = await provider.diagnose(json_error_bundle, "n1")
    assert result.error_category == "bad_json"
