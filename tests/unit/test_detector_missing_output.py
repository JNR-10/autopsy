from autopsy.core.events import (
    AgentEndEvent, EventKind, LLMRequestEvent, LLMResponseEvent,
)
from autopsy.detectors.missing_output import MissingOutputDetector

SID = "01HXY000000000000000000001"


def test_fails_when_llm_ran_but_no_output():
    d = MissingOutputDetector()
    events = [
        LLMRequestEvent(
            event_id="01HXY000000000000000000001",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=1, kind=EventKind.LLM_REQUEST, model="m",
        ),
        LLMResponseEvent(
            event_id="01HXY000000000000000000002",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=2, kind=EventKind.LLM_RESPONSE,
            model="m", content="",
        ),
    ]
    v = d.evaluate(events, outcome="ok")
    assert v is not None and v.verdict == "fail"


def test_passes_when_agent_end_has_output():
    d = MissingOutputDetector()
    events = [
        AgentEndEvent(
            event_id="01HXY000000000000000000003",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=3, kind=EventKind.AGENT_END,
            duration_ms=1.0, output_preview="done",
        ),
    ]
    assert d.evaluate(events, outcome="ok") is None
