"""E2E: additional detectors promote sessions under sample=errors."""
from __future__ import annotations

import json
import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.context import current_session
from autopsy.core.decorator import LensDecorator
from autopsy.core.events import EventKind, ErrorEvent, ToolCallEndEvent
from autopsy.core.session import get_writer
from autopsy.core.ulid import new_ulid


@pytest.fixture
def wired_tool_failure(tmp_path, monkeypatch):
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        enabled_detectors=["tool_failure"],
    )
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


@pytest.fixture
def wired_unhandled(tmp_path, monkeypatch):
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        enabled_detectors=["unhandled_exception"],
    )
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _wait_dir(tmp_path):
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        sd = tmp_path / "sessions"
        if sd.exists():
            for p in sd.iterdir():
                if (p / "manifest.json").exists():
                    return p
        time.sleep(0.02)
    return None


def _emit_tool_end(*, error: str | None = None) -> None:
    session = current_session()
    assert session is not None
    session.record_event(ToolCallEndEvent(
        event_id=new_ulid(),
        parent_id=None,
        session_id=session.session_id,
        trace_id=session.session_id,
        timestamp_ns=time.time_ns(),
        kind=EventKind.TOOL_CALL_END,
        tool_name="search",
        error=error,
    ))


def _emit_error(*, handled: bool = False) -> None:
    session = current_session()
    assert session is not None
    session.record_event(ErrorEvent(
        event_id=new_ulid(),
        parent_id=None,
        session_id=session.session_id,
        trace_id=session.session_id,
        timestamp_ns=time.time_ns(),
        kind=EventKind.ERROR,
        error_type="ValueError",
        error_message="oops",
        traceback="",
        attributes={"handled": handled} if handled else {},
    ))


def test_tool_failure_e2e(wired_tool_failure):
    lens, tmp_path = wired_tool_failure

    @lens.trace
    def agent():
        _emit_tool_end(error="timeout")
        return "x"

    assert agent() == "x"
    sd = _wait_dir(tmp_path)
    assert sd is not None
    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["status"] == "error"
    assert manifest["error_type"] == "detector:tool_failure"


def test_unhandled_exception_e2e(wired_unhandled):
    lens, tmp_path = wired_unhandled

    @lens.trace
    def agent():
        _emit_error()
        return "x"

    assert agent() == "x"
    sd = _wait_dir(tmp_path)
    assert sd is not None
    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["error_type"] == "detector:unhandled_exception"


def _load_events(session_dir):
    import gzip

    gz = session_dir / "events.jsonl.gz"
    plain = session_dir / "events.jsonl"
    if gz.exists():
        with gzip.open(gz, "rt") as f:
            return [json.loads(line) for line in f if line.strip()]
    if plain.exists():
        with plain.open("r") as f:
            return [json.loads(line) for line in f if line.strip()]
    return []


def test_handled_error_skips_unhandled(wired_unhandled):
    lens, tmp_path = wired_unhandled

    @lens.trace
    def agent():
        _emit_error(handled=True)
        return "x"

    assert agent() == "x"
    sd = _wait_dir(tmp_path)
    assert sd is not None
    verdicts = [
        e for e in _load_events(sd)
        if e.get("kind") == "detector_verdict"
    ]
    assert not any(
        v.get("detector_name") == "unhandled_exception" for v in verdicts
    )
    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest.get("error_type") != "detector:unhandled_exception"
