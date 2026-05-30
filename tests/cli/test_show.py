"""Tests for autopsy show command."""
from __future__ import annotations

import json

import pytest

from autopsy.cli.main import cli

SHOW_JSON_KEYS = frozenset({
    "session_id",
    "agent_name",
    "status",
    "error_type",
    "duration_ms",
    "stats",
    "detector_verdicts",
    "errors",
})


@pytest.fixture(autouse=True)
def cli_autopsy_root(session_root, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(session_root))


def test_show_not_found(cli_runner):
    result = cli_runner.invoke(cli, ["show", "missing-session-id"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_show_human_contains_detector_section(cli_runner, writer_session_detector_fail):
    sid = writer_session_detector_fail
    result = cli_runner.invoke(cli, ["show", sid])
    assert result.exit_code == 0
    out = result.output.lower()
    assert "detector" in out
    assert "empty_response" in result.output
    assert "fail" in out


def test_show_json_keys(cli_runner, writer_session_detector_fail):
    sid = writer_session_detector_fail
    result = cli_runner.invoke(cli, ["show", sid, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert SHOW_JSON_KEYS <= data.keys()
    assert data["status"] == "error"
    assert data["error_type"] == "detector:empty_response"
    assert data["stats"]["tokens"] >= 0
    assert any(v["name"] == "empty_response" for v in data["detector_verdicts"])
    assert data["detector_verdicts"][0]["verdict"] == "fail"


def test_show_ok_session_human(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["show", writer_session_ok])
    assert result.exit_code == 0
    assert "success" in result.output.lower()
    assert writer_session_ok[:12] in result.output


def test_show_events_flag(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["show", writer_session_ok, "--events"])
    assert result.exit_code == 0
    assert "Events" in result.output or "events" in result.output.lower()
