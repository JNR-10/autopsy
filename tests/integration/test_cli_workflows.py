"""Integration tests: Writer-backed sessions through CLI commands."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

import autopsy.core.session as session_mod
from autopsy.cli.main import cli
from autopsy.core.config import LensConfig
from autopsy.core.events import AgentEndEvent, AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer

from tests.cli.conftest import OK_SID, _wait_for_manifest


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def test_ls_workflow_after_writer(cli_runner, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            OK_SID, sample=SampleMode.ALL, agent_name="workflow-agent", start_ns=1,
        )
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000F",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=1,
            kind=EventKind.AGENT_START,
            agent_name="workflow-agent",
        ))
        w.enqueue(AgentEndEvent(
            event_id="01HXY00000000000000000000G",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=2,
            kind=EventKind.AGENT_END,
            duration_ms=5.0,
        ))
        w.end_session(OK_SID, outcome="ok")
        _wait_for_manifest(tmp_path, OK_SID)
    finally:
        w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)

    result = cli_runner.invoke(cli, ["ls"])
    assert result.exit_code == 0
    assert "workflow" in result.output
    assert "success" in result.output

    j = cli_runner.invoke(cli, ["ls", "--json"])
    assert j.exit_code == 0
    rows = json.loads(j.output)
    assert any(r["session_id"] == OK_SID for r in rows)


def test_show_workflow_detector_fail(cli_runner, tmp_path, monkeypatch):
    """Writer detector-fail session → show contains empty_response verdict."""
    import autopsy.core.session as session_mod
    from autopsy.core.config import LensConfig
    from autopsy.core.events import EventKind, LLMResponseEvent
    from autopsy.core.session import Session, get_writer

    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    s = Session.begin(config=cfg, agent_name="workflow-fail-agent", sample="errors")
    s.record_event(LLMResponseEvent(
        event_id="01HXY00000000000000000000H",
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
    _wait_for_manifest(tmp_path, s.session_id)

    result = cli_runner.invoke(cli, ["show", s.session_id])
    assert result.exit_code == 0
    assert "empty_response" in result.output


def test_diagnose_workflow_json(cli_runner, tmp_path, monkeypatch):
    """Writer session → diagnose --json with mocked agent."""
    from autopsy.diagnostics.types import DiagnosisResult

    class _FakeAgent:
        async def diagnose(self, bundle, node_id=None):
            return DiagnosisResult(root_cause="workflow cause", confidence=0.9)

    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(
        "autopsy.cli.main._make_diagnose_agent",
        lambda model, bundle: _FakeAgent(),
    )

    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            OK_SID, sample=SampleMode.ALL, agent_name="diag-agent", start_ns=1,
        )
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000I",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=1,
            kind=EventKind.AGENT_START,
            agent_name="diag-agent",
        ))
        w.enqueue(AgentEndEvent(
            event_id="01HXY00000000000000000000J",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=2,
            kind=EventKind.AGENT_END,
            duration_ms=1.0,
        ))
        w.end_session(OK_SID, outcome="ok")
        _wait_for_manifest(tmp_path, OK_SID)
    finally:
        w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)

    result = cli_runner.invoke(cli, ["diagnose", OK_SID, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["root_cause"] == "workflow cause"
    assert data["confidence"] == 0.9


def test_tail_workflow_finalized(cli_runner, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            OK_SID, sample=SampleMode.ALL, agent_name="tail-agent", start_ns=1,
        )
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000K",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=1,
            kind=EventKind.AGENT_START,
            agent_name="tail-agent",
        ))
        w.end_session(OK_SID, outcome="ok")
        _wait_for_manifest(tmp_path, OK_SID)
    finally:
        w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)

    result = cli_runner.invoke(cli, ["tail", OK_SID, "--lines", "5"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_export_import_workflow(cli_runner, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            OK_SID, sample=SampleMode.ALL, agent_name="export-agent", start_ns=1,
        )
        w.end_session(OK_SID, outcome="ok")
        _wait_for_manifest(tmp_path, OK_SID)
    finally:
        w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)

    archive = tmp_path / "roundtrip.tar.gz"
    exp = cli_runner.invoke(cli, ["export", "--out", str(archive)])
    assert exp.exit_code == 0

    import_dir = tmp_path / "imported"
    import_dir.mkdir()
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(import_dir))
    imp = cli_runner.invoke(cli, ["import", str(archive)])
    assert imp.exit_code == 0

    ls = cli_runner.invoke(cli, ["ls", "--json"])
    rows = json.loads(ls.output)
    assert any(r["session_id"] == OK_SID for r in rows)


def test_clean_workflow(cli_runner, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            OK_SID, sample=SampleMode.ALL, agent_name="clean-agent", start_ns=1,
        )
        w.end_session(OK_SID, outcome="ok")
        _wait_for_manifest(tmp_path, OK_SID)
    finally:
        w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)

    before = cli_runner.invoke(cli, ["ls", "--json"])
    assert len(json.loads(before.output)) >= 1

    clean = cli_runner.invoke(cli, ["clean", "--all"])
    assert clean.exit_code == 0

    after = cli_runner.invoke(cli, ["ls", "--json"])
    assert json.loads(after.output) == []
