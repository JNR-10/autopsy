"""Tests for extended built-in failure detectors."""
from __future__ import annotations

from autopsy.core.events import (
    ErrorEvent,
    EventKind,
    LLMRequestEvent,
    LLMResponseEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from autopsy.detectors.content_filter import ContentFilterDetector
from autopsy.detectors.duplicate_tool_args import DuplicateToolArgsDetector
from autopsy.detectors.llm_tool_without_execution import LLMToolWithoutExecutionDetector
from autopsy.detectors.orphan_llm import OrphanLLMDetector
from autopsy.detectors.orphan_tool_call import OrphanToolCallDetector
from autopsy.detectors.registry import builtin_detectors
from autopsy.detectors.token_budget_empty import TokenBudgetEmptyDetector
from autopsy.detectors.tool_failure import ToolFailureDetector
from autopsy.detectors.truncated_output import TruncatedOutputDetector
from autopsy.detectors.error_storm import ErrorStormDetector
from autopsy.detectors.high_latency import HighLatencyDetector
from autopsy.detectors.unhandled_exception import UnhandledExceptionDetector


def _tool_start(i: int, name: str = "search") -> ToolCallStartEvent:
    return ToolCallStartEvent(
        event_id=f"01HXY00000000000000000{i:04d}",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=i,
        kind=EventKind.TOOL_CALL_START,
        tool_name=name,
        tool_args={"q": "x"},
    )


def _tool_end(i: int, *, error: str | None = None) -> ToolCallEndEvent:
    return ToolCallEndEvent(
        event_id=f"01HXY00000000000000001{i:04d}",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=i,
        kind=EventKind.TOOL_CALL_END,
        tool_name="search",
        error=error,
    )


def _llm_resp(i: int, **kwargs) -> LLMResponseEvent:
    return LLMResponseEvent(
        event_id=f"01HXY00000000000000002{i:04d}",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=i,
        kind=EventKind.LLM_RESPONSE,
        model="gpt-test",
        **kwargs,
    )


def test_builtin_detector_count():
    assert len(builtin_detectors()) == 14


def test_tool_failure_on_error_end():
    det = ToolFailureDetector()
    v = det.evaluate([_tool_end(1, error="timeout")], outcome="ok")
    assert v is not None and v.detector_name == "tool_failure"


def test_truncated_output_length():
    det = TruncatedOutputDetector()
    v = det.evaluate([_llm_resp(1, finish_reason="length")], outcome="ok")
    assert v is not None


def test_orphan_tool_call():
    det = OrphanToolCallDetector()
    v = det.evaluate([_tool_start(1), _tool_start(2)], outcome="ok")
    assert v is not None


def test_orphan_tool_call_balanced_passes():
    det = OrphanToolCallDetector()
    assert det.evaluate([_tool_start(1), _tool_end(2)], outcome="ok") is None


def test_orphan_llm():
    det = OrphanLLMDetector()
    req = LLMRequestEvent(
        event_id="01HXY00000000000000000001",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=1,
        kind=EventKind.LLM_REQUEST,
        model="m",
    )
    v = det.evaluate([req], outcome="ok")
    assert v is not None


def test_llm_tool_without_execution():
    det = LLMToolWithoutExecutionDetector()
    v = det.evaluate(
        [_llm_resp(1, tool_calls=[{"id": "1", "name": "search"}])],
        outcome="ok",
    )
    assert v is not None


def test_unhandled_exception_when_outcome_ok():
    det = UnhandledExceptionDetector()
    err = ErrorEvent(
        event_id="01HXY00000000000000000003",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=3,
        kind=EventKind.ERROR,
        error_type="ValueError",
        error_message="bad",
        traceback="",
    )
    v = det.evaluate([err], outcome="ok")
    assert v is not None


def test_token_budget_empty():
    det = TokenBudgetEmptyDetector()
    v = det.evaluate([_llm_resp(1, completion_tokens=100, content="")], outcome="ok")
    assert v is not None


def test_content_filter():
    det = ContentFilterDetector()
    v = det.evaluate([_llm_resp(1, finish_reason="content_filter")], outcome="ok")
    assert v is not None


def test_duplicate_tool_args():
    from autopsy.core.config import LensConfig

    det = DuplicateToolArgsDetector(config=LensConfig(duplicate_tool_threshold=2))
    events = [_tool_start(1), _tool_start(2)]
    v = det.evaluate(events, outcome="ok")
    assert v is not None


def test_llm_tool_with_execution_passes():
    det = LLMToolWithoutExecutionDetector()
    events = [
        _llm_resp(1, tool_calls=[{"id": "1"}]),
        _tool_start(2),
        _tool_end(3),
    ]
    assert det.evaluate(events, outcome="ok") is None


def test_llm_tool_fails_when_next_turn_without_tool():
    det = LLMToolWithoutExecutionDetector()
    req = LLMRequestEvent(
        event_id="01HXY00000000000000000099",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=4,
        kind=EventKind.LLM_REQUEST,
        model="m",
    )
    events = [
        _llm_resp(1, tool_calls=[{"id": "1"}]),
        _tool_start(2),
        req,
        _llm_resp(5, tool_calls=[{"id": "2"}]),
    ]
    v = det.evaluate(events, outcome="ok")
    assert v is not None


def test_unhandled_skips_handled_attribute():
    det = UnhandledExceptionDetector()
    err = ErrorEvent(
        event_id="01HXY00000000000000000004",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=4,
        kind=EventKind.ERROR,
        error_type="ValueError",
        error_message="caught",
        traceback="",
        attributes={"handled": True},
    )
    assert det.evaluate([err], outcome="ok") is None


def test_high_latency_warn():
    from autopsy.core.config import LensConfig

    det = HighLatencyDetector(config=LensConfig(latency_threshold_ms=100))
    v = det.evaluate([_llm_resp(1, latency_ms=500.0)], outcome="ok")
    assert v is not None and v.verdict == "warn"


def test_error_storm_warn():
    from autopsy.core.config import LensConfig

    det = ErrorStormDetector(config=LensConfig(error_storm_threshold=2))
    errors = [
        ErrorEvent(
            event_id=f"01HXY00000000000000000{i:04d}",
            parent_id=None,
            session_id="s",
            trace_id="s",
            timestamp_ns=i,
            kind=EventKind.ERROR,
            error_type="E",
            error_message="x",
            traceback="",
        )
        for i in range(2)
    ]
    v = det.evaluate(errors, outcome="error")
    assert v is not None and v.verdict == "warn"
