"""Tests for autopsy ls / sessions commands."""
from __future__ import annotations

import json

import pytest

from autopsy.cli.main import cli

LS_JSON_KEYS = frozenset({
    "session_id", "agent", "status", "errors", "detector", "duration_ms", "created",
})


@pytest.fixture(autouse=True)
def cli_autopsy_root(session_root, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(session_root))


def test_ls_empty_state(cli_runner):
    result = cli_runner.invoke(cli, ["ls"])
    assert result.exit_code == 0
    assert "No sessions" in result.output


def test_ls_human_output_contains_status(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["ls"])
    assert result.exit_code == 0
    assert writer_session_ok[:10] in result.output
    assert "ok-agent" in result.output
    assert "success" in result.output


def test_ls_json_schema(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["ls", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert isinstance(rows, list)
    assert len(rows) >= 1
    row = next(r for r in rows if r["session_id"] == writer_session_ok)
    assert LS_JSON_KEYS <= row.keys()
    assert row["status"] == "success"
    assert row["detector"] == "-"


def test_ls_detector_column_for_fail(cli_runner, writer_session_detector_fail):
    sid = writer_session_detector_fail
    result = cli_runner.invoke(cli, ["ls"])
    assert result.exit_code == 0
    assert "fail-age" in result.output
    assert "error" in result.output
    assert "empty_re" in result.output

    j = cli_runner.invoke(cli, ["ls", "--json"])
    rows = json.loads(j.output)
    row = next(r for r in rows if r["session_id"] == sid)
    assert row["detector"] == "empty_response"
    assert row["status"] == "error"


def test_sessions_alias_matches_ls(cli_runner, writer_session_ok):
    ls = cli_runner.invoke(cli, ["ls", "--json"])
    sessions = cli_runner.invoke(cli, ["sessions", "--json"])
    assert ls.exit_code == 0
    assert sessions.exit_code == 0
    assert json.loads(ls.output) == json.loads(sessions.output)
