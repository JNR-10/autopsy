"""Integration tests for diagnose provider wiring in CLI and server."""
from __future__ import annotations

import json
import time

import httpx
import pytest
from click.testing import CliRunner

from autopsy.cli.main import cli
from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.events import AgentEndEvent, AgentStartEvent, EventKind
from autopsy.core.session import get_writer
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer
from autopsy.diagnostics.types import DiagnosisResult
from autopsy.server.app import create_app

from tests.cli.conftest import OK_SID, _wait_for_manifest


class _StubProvider:
    name = "stub"

    async def diagnose(self, bundle, node_id=None):
        return DiagnosisResult(
            root_cause="wiring ok",
            error_category="logic",
            confidence=0.99,
        )


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def test_cli_diagnose_uses_provider_factory(cli_runner, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(
        "autopsy.diagnostics.provider.resolve_diagnose_provider",
        lambda *args, **kwargs: _StubProvider(),
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
            event_id="01HXY00000000000000000000F",
            parent_id=None,
            session_id=OK_SID,
            trace_id=OK_SID,
            timestamp_ns=1,
            kind=EventKind.AGENT_START,
            agent_name="diag-agent",
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

    result = cli_runner.invoke(cli, ["diagnose", OK_SID, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["root_cause"] == "wiring ok"


@pytest.fixture
def lens_with_tmp_store(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path
    get_writer(cfg).shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _latest_session_id(tmp_path) -> str:
    reader = LegacyBundleReader(root=tmp_path)
    deadline = time.monotonic() + 2.0
    rows = []
    while time.monotonic() < deadline:
        rows = reader.list()
        if rows:
            break
        time.sleep(0.02)
    assert rows, "expected at least one session on disk"
    return rows[0]["session_id"]


@pytest.mark.asyncio
async def test_server_diagnose_uses_provider_factory(
    lens_with_tmp_store, monkeypatch,
):
    lens, tmp_path = lens_with_tmp_store
    monkeypatch.setattr(
        "autopsy.server.app._bundle_reader",
        lambda: LegacyBundleReader(root=tmp_path),
    )
    monkeypatch.setattr(
        "autopsy.diagnostics.provider.resolve_diagnose_provider",
        lambda *args, **kwargs: _StubProvider(),
    )

    @lens.trace(name="bad")
    async def bad():
        raise ValueError("oops")

    with pytest.raises(ValueError):
        await bad()

    sid = _latest_session_id(tmp_path)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(f"/api/sessions/{sid}/diagnose", json={})
    assert r.status_code == 200
    assert r.json()["root_cause"] == "wiring ok"
