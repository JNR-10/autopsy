from autopsy.core.events import EventKind, LLMResponseEvent
from autopsy.detectors.empty_response import EmptyResponseDetector

SID = "01HXY000000000000000000001"


def _llm(content: str) -> LLMResponseEvent:
    return LLMResponseEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None, session_id=SID, trace_id=SID,
        timestamp_ns=1, kind=EventKind.LLM_RESPONSE,
        model="m", content=content,
    )


def test_fails_on_empty_last_response():
    d = EmptyResponseDetector()
    v = d.evaluate([_llm("   ")], outcome="ok")
    assert v is not None
    assert v.verdict == "fail"
    assert "empty" in v.reason.lower()


def test_passes_on_nonempty_response():
    d = EmptyResponseDetector()
    assert d.evaluate([_llm("hello")], outcome="ok") is None


def test_skips_when_no_llm_response():
    d = EmptyResponseDetector()
    assert d.evaluate([], outcome="ok") is None
