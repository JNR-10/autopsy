"""Event codec: JSONL default and optional msgspec frames."""
from __future__ import annotations

import json

import pytest

from autopsy.core.config import LensConfig, load_config_from_env
from autopsy.core.event_codec import (
    encode_events_chunk,
    load_session_event_dicts,
    msgspec_available,
    normalize_event_encoding,
)
from autopsy.core.events import AgentStartEvent, EventKind, Manifest
from autopsy.core.store.local_fs import LocalFilesystemStore


def _agent_start(sid: str) -> AgentStartEvent:
    return AgentStartEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=1,
        kind=EventKind.AGENT_START,
        agent_name="a",
    )


@pytest.mark.skipif(not msgspec_available(), reason="msgspec not installed")
def test_msgpack_roundtrip_via_store(tmp_path):
    sid = "01HXY000000000000000000001"
    store = LocalFilesystemStore(root=tmp_path, event_encoding="msgspec")
    ev = _agent_start(sid)
    store.write_events(sid, [ev])
    store.finalize_session(Manifest(
        session_id=sid,
        agent_name="a",
        start_time_ns=1,
        end_time_ns=2,
        duration_ms=1.0,
        status="ok",
        event_count=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=1,
        monotonic_ns_at_start=1,
    ))
    loaded = store.load_session(sid)
    assert loaded is not None
    assert len(loaded["events"]) == 1
    assert loaded["events"][0]["kind"] == "agent_start"
    assert loaded["manifest"]["extra"]["event_encoding"] == "msgspec"
    gz = tmp_path / "sessions" / sid / "events.msgpack.gz"
    assert gz.exists()


@pytest.mark.skipif(not msgspec_available(), reason="msgspec not installed")
def test_encode_chunk_smaller_than_json_for_large_preview():
    sid = "01HXY000000000000000000002"
    ev = _agent_start(sid)
    ev = ev.model_copy(update={"input_preview": "x" * 2000})
    json_bytes = encode_events_chunk([ev], "json")
    msgpack_bytes = encode_events_chunk([ev], "msgspec")
    assert len(msgpack_bytes) < len(json_bytes)


def test_load_session_dicts_reads_json_and_msgpack(tmp_path):
    sid = "01HXY000000000000000000003"
    sd = tmp_path / "sessions" / sid
    sd.mkdir(parents=True)
    line = json.dumps({
        "event_id": "01HXY00000000000000000000A",
        "parent_id": None,
        "session_id": sid,
        "trace_id": sid,
        "timestamp_ns": 1,
        "kind": "agent_start",
        "agent_name": "a",
    })
    (sd / "events.jsonl").write_text(line + "\n")
    assert len(load_session_event_dicts(sd)) == 1

    if not msgspec_available():
        return
    sid2 = "01HXY000000000000000000004"
    store = LocalFilesystemStore(root=tmp_path, event_encoding="msgspec")
    store.write_events(sid2, [_agent_start(sid2)])
    assert len(load_session_event_dicts(tmp_path / "sessions" / sid2)) == 1


def test_env_encoding_falls_back_without_msgspec(monkeypatch):
    monkeypatch.setenv("AUTOPSY_EVENT_ENCODING", "msgspec")
    pytest.importorskip("msgspec")
    assert load_config_from_env(LensConfig()).event_encoding == "msgspec"

    import builtins
    real_import = builtins.__import__

    def block_msgspec(name, *args, **kwargs):
        if name == "msgspec":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_msgspec)
    assert normalize_event_encoding("msgspec") == "json"
