"""Tests for autopsy diagnose command."""
from __future__ import annotations

import json

import pytest

from autopsy.cli.main import cli
from autopsy.diagnostics.types import DiagnosisResult

DIAGNOSE_JSON_KEYS = frozenset({
    "root_cause",
    "affected_node_id",
    "affected_node_name",
    "error_category",
    "fix_suggestion",
    "fix_code_snippet",
    "confidence",
    "latency_insight",
    "estimated_latency_savings_ms",
    "model_swap_suggestion",
    "raw_response",
})


class _FakeAgent:
    async def diagnose(self, bundle, node_id=None):
        return DiagnosisResult(
            root_cause="mock root cause",
            affected_node_id="node-1",
            affected_node_name="test-node",
            error_category="logic",
            fix_suggestion="mock fix",
            confidence=0.85,
        )


@pytest.fixture(autouse=True)
def cli_autopsy_root(session_root, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(session_root))


@pytest.fixture(autouse=True)
def mock_diagnose_agent(monkeypatch):
    monkeypatch.setattr(
        "autopsy.cli.main._make_diagnose_agent",
        lambda model, bundle: _FakeAgent(),
    )


def test_diagnose_not_found(cli_runner):
    result = cli_runner.invoke(cli, ["diagnose", "missing-session-id"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_diagnose_prefix_match(cli_runner, writer_session_ok, monkeypatch):
    prefix = writer_session_ok[:8]
    result = cli_runner.invoke(cli, ["diagnose", prefix])
    assert result.exit_code == 0
    assert "mock root cause" in result.output


def test_diagnose_json_keys(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["diagnose", writer_session_ok, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert DIAGNOSE_JSON_KEYS <= data.keys()
    assert data["root_cause"] == "mock root cause"
    assert data["confidence"] == 0.85


def test_diagnose_json_no_rich_noise(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["diagnose", writer_session_ok, "--json"])
    assert result.exit_code == 0
    assert "Diagnosing" not in result.output
    json.loads(result.output)
