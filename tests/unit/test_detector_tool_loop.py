from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, ToolCallStartEvent
from autopsy.detectors.tool_loop import ToolLoopDetector

SID = "01HXY000000000000000000001"


def _tool(name: str, seq: str) -> ToolCallStartEvent:
    return ToolCallStartEvent(
        event_id=f"01HXY0000000000000000000{seq}",
        parent_id=None, session_id=SID, trace_id=SID,
        timestamp_ns=int(seq), kind=EventKind.TOOL_CALL_START,
        tool_name=name, tool_args={},
    )


def test_fails_on_consecutive_same_tool():
    cfg = LensConfig(tool_loop_threshold=3)
    d = ToolLoopDetector(config=cfg)
    events = [_tool("search", str(i)) for i in range(3)]
    v = d.evaluate(events, outcome="ok")
    assert v is not None and v.verdict == "fail"


def test_passes_on_alternating_tools():
    cfg = LensConfig(tool_loop_threshold=3)
    d = ToolLoopDetector(config=cfg)
    events = [_tool("a", "1"), _tool("b", "2"), _tool("a", "3")]
    assert d.evaluate(events, outcome="ok") is None
