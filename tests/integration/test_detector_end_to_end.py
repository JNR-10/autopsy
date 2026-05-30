"""End-to-end: semantic failure detection promotes session under sample=errors."""
from __future__ import annotations

import asyncio
import gzip
import json
import time
import types

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.context import current_session
from autopsy.core.decorator import LensDecorator
from autopsy.core.events import EventKind, ToolCallStartEvent
from autopsy.core.interceptor import InterceptorManager
from autopsy.core.session import get_writer
from autopsy.core.ulid import new_ulid


class _FakeEmptyAsync:
    async def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(
                prompt_tokens=1, completion_tokens=0, total_tokens=1,
            ),
        )


class _FakeEmptySync:
    def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(
                prompt_tokens=1, completion_tokens=0, total_tokens=1,
            ),
        )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    fake_async = _FakeEmptyAsync()
    fake_sync = _FakeEmptySync()
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (fake_async, fake_sync),
    )
    mgr = InterceptorManager()
    mgr.install()
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path, cfg, fake_async
    mgr.uninstall()
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


@pytest.fixture
def wired_tool_loop(tmp_path, monkeypatch):
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        enabled_detectors=["tool_loop"],
        tool_loop_threshold=3,
    )
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path, cfg
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _session_dir(tmp_path):
    sd = tmp_path / "sessions"
    if not sd.exists():
        return None
    rows = [p for p in sd.iterdir() if (p / "manifest.json").exists()]
    return rows[0] if rows else None


def _wait_for_session(tmp_path):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        sd = _session_dir(tmp_path)
        if sd is not None:
            return sd
        time.sleep(0.02)
    return _session_dir(tmp_path)


def _load_events(session_dir):
    gz = session_dir / "events.jsonl.gz"
    plain = session_dir / "events.jsonl"
    if gz.exists():
        with gzip.open(gz, "rt") as f:
            return [json.loads(line) for line in f if line.strip()]
    if plain.exists():
        with plain.open("r") as f:
            return [json.loads(line) for line in f if line.strip()]
    return []


def _emit_tool_start(tool_name: str) -> None:
    """Simulate tool-call capture until first-class tool instrumentation ships."""
    session = current_session()
    if session is None:
        return
    session.record_event(ToolCallStartEvent(
        event_id=new_ulid(),
        parent_id=None,
        session_id=session.session_id,
        trace_id=session.session_id,
        timestamp_ns=time.time_ns(),
        kind=EventKind.TOOL_CALL_START,
        tool_name=tool_name,
        tool_args={},
    ))


def test_semantic_failure_empty_llm_response_keeps_session(wired):
    """Empty LLM content under errors sampling triggers detector_verdict + status=error."""
    lens, tmp_path, cfg, fake_async = wired

    @lens.trace
    async def agent(q):
        await fake_async.create(
            model="gpt-test", messages=[{"role": "user", "content": q}],
        )
        return ""

    asyncio.run(agent("hi"))

    sd = _wait_for_session(tmp_path)
    assert sd is not None

    events = _load_events(sd)
    kinds = [e["kind"] for e in events]
    assert "llm_response" in kinds
    assert "detector_verdict" in kinds

    verdicts = [e for e in events if e["kind"] == "detector_verdict"]
    assert any(v["verdict"] == "fail" for v in verdicts)
    assert any(v["detector_name"] == "empty_response" for v in verdicts)

    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["status"] == "error"
    assert manifest["error_type"] == "detector:empty_response"


def test_semantic_failure_tool_loop_keeps_session(wired_tool_loop):
    """Repeated same-tool calls under errors sampling trigger tool_loop detector."""
    lens, tmp_path, cfg = wired_tool_loop

    @lens.trace
    def agent():
        for _ in range(3):
            _emit_tool_start("search")
        return "done"

    assert agent() == "done"

    sd = _wait_for_session(tmp_path)
    assert sd is not None

    events = _load_events(sd)
    tool_starts = [e for e in events if e["kind"] == "tool_call_start"]
    assert len(tool_starts) == 3

    verdicts = [e for e in events if e["kind"] == "detector_verdict"]
    assert any(v["verdict"] == "fail" for v in verdicts)
    assert any(v["detector_name"] == "tool_loop" for v in verdicts)
    assert any("search" in v.get("reason", "") for v in verdicts)

    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["status"] == "error"
    assert manifest["error_type"] == "detector:tool_loop"
