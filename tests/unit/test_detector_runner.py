"""Tests for DetectorRunner."""
from __future__ import annotations

from autopsy.core.events import (
    DetectorVerdictEvent, EventKind,
)
from autopsy.detectors.runner import run_detectors


class _FailDetector:
    name = "fail"

    def evaluate(self, events, *, outcome: str):
        return DetectorVerdictEvent(
            event_id="01HXY000000000000000000001",
            parent_id=None, session_id="s", trace_id="s",
            timestamp_ns=1, kind=EventKind.DETECTOR_VERDICT,
            detector_name="fail", verdict="fail", reason="bad",
        )


class _BrokenDetector:
    name = "broken"

    def evaluate(self, events, *, outcome: str):
        raise RuntimeError("boom")


def test_runner_returns_verdicts():
    out = run_detectors(
        events=[], outcome="ok", session_id="s", trace_id="s",
        parent_id=None, detectors=[_FailDetector()],
    )
    assert len(out) == 1
    assert out[0].verdict == "fail"


def test_runner_isolates_exceptions():
    out = run_detectors(
        events=[], outcome="ok", session_id="s", trace_id="s",
        parent_id=None, detectors=[_BrokenDetector(), _FailDetector()],
    )
    assert len(out) == 1
    assert out[0].detector_name == "fail"
