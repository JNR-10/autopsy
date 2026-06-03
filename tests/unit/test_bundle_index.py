"""v1-native node_index synthesis for dashboard consumers."""
from __future__ import annotations

from autopsy.core.bundle_index import build_legacy_dag_edges, build_legacy_node_index
from autopsy.core.compat import read_v1_bundle
from autopsy.core.config import LensConfig
from autopsy.core.events import AgentEndEvent, AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000042"


def test_build_node_index_from_legacy_events():
    events = [
        {"event_type": "node_start", "node_id": "a", "node_name": "root", "parent_node_id": None},
        {"event_type": "node_end", "node_id": "a", "duration_ms": 10.0},
    ]
    idx = build_legacy_node_index(events)
    assert "a" in idx
    assert idx["a"]["end_event"]["duration_ms"] == 10.0
    assert build_legacy_dag_edges(events) == []


def test_read_v1_bundle_has_node_index(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ALL, agent_name="agent", start_ns=1)
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=1, kind=EventKind.AGENT_START, agent_name="agent",
        ))
        w.enqueue(AgentEndEvent(
            event_id="01HXY00000000000000000000B",
            parent_id="01HXY00000000000000000000A",
            session_id=SID, trace_id=SID,
            timestamp_ns=2, kind=EventKind.AGENT_END, duration_ms=5.0,
            output_preview="done",
        ))
        w.end_session(
            SID, outcome="ok",
            bundle_meta={
                "agent_module_path": "/tmp/agent.py",
                "agent_fn_name": "m.run",
                "input_query": "hello",
                "replay_checkpoints": {"01HXY00000000000000000000A": "done"},
            },
        )
        import time
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / SID / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)

    bundle = read_v1_bundle(tmp_path / "sessions" / SID)
    assert bundle is not None
    assert bundle["node_index"]
    assert bundle["agent_module_path"] == "/tmp/agent.py"
    assert bundle["replay_checkpoints"]["01HXY00000000000000000000A"] == "done"
