"""CLI test fixtures: CliRunner and Writer-backed session dirs."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

import autopsy.core.session as session_mod
from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.events import (
    AgentEndEvent,
    AgentStartEvent,
    EventKind,
    LLMResponseEvent,
)
from autopsy.core.session import Session, get_writer
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer

OK_SID = "01HXY00000000000000000000A"
DETECTOR_FAIL_SID = "01HXY00000000000000000000B"


def _wait_for_manifest(root: Path, session_id: str, timeout: float = 2.0) -> None:
    manifest = root / "sessions" / session_id / "manifest.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manifest.exists():
            return
        time.sleep(0.02)
    assert manifest.exists(), f"manifest missing for {session_id}"


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def session_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def writer_session_ok(session_root: Path) -> str:
    """Successful session on disk (sample=all)."""
    store = LocalFilesystemStore(root=session_root)
    cfg = LensConfig(session_dir=str(session_root), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            OK_SID, sample=SampleMode.ALL, agent_name="ok-agent", start_ns=1,
        )
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000C",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=1,
            kind=EventKind.AGENT_START,
            agent_name="ok-agent",
        ))
        w.enqueue(AgentEndEvent(
            event_id="01HXY00000000000000000000D",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=2,
            kind=EventKind.AGENT_END,
            duration_ms=1.0,
        ))
        w.end_session(OK_SID, outcome="ok")
        _wait_for_manifest(session_root, OK_SID)
    finally:
        w.shutdown(timeout=2.0)
    return OK_SID


@pytest.fixture
def writer_session_detector_fail(session_root: Path, monkeypatch) -> str:
    """Session promoted by empty_response detector under errors sampling."""
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(session_root), default_sample="errors")
    s = Session.begin(config=cfg, agent_name="fail-agent", sample="errors")
    s.record_event(LLMResponseEvent(
        event_id="01HXY00000000000000000000E",
        parent_id=None,
        session_id=s.session_id,
        trace_id=s.session_id,
        timestamp_ns=1,
        kind=EventKind.LLM_RESPONSE,
        model="m",
        content="  ",
    ))
    s.end(outcome="ok")
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    _wait_for_manifest(session_root, s.session_id)
    manifest = json.loads(
        (session_root / "sessions" / s.session_id / "manifest.json").read_text(),
    )
    assert manifest["status"] == "error"
    assert manifest["error_type"] == "detector:empty_response"
    return s.session_id


@pytest.fixture
def bundle_reader(session_root: Path) -> LegacyBundleReader:
    return LegacyBundleReader(root=session_root)
