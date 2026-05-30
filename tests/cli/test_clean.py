"""Tests for autopsy clean command."""
from __future__ import annotations

import json

import pytest

from autopsy.cli.main import cli


@pytest.fixture(autouse=True)
def cli_autopsy_root(session_root, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(session_root))


def test_clean_requires_all_flag(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["clean"])
    assert result.exit_code == 0
    assert "--all" in result.output


def test_clean_all_removes_v1_directories(cli_runner, writer_session_ok, session_root):
    sid = writer_session_ok
    session_dir = session_root / "sessions" / sid
    assert session_dir.is_dir()

    result = cli_runner.invoke(cli, ["clean", "--all"])
    assert result.exit_code == 0
    assert "deleted" in result.output.lower()
    assert not session_dir.exists()

    ls = cli_runner.invoke(cli, ["ls", "--json"])
    rows = json.loads(ls.output)
    assert rows == []


def test_clean_all_removes_v0_json_blobs(cli_runner, session_root):
    blob = session_root / "sessions" / "legacy-session.json"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_text(json.dumps({"session_id": "legacy-session", "events": []}))

    result = cli_runner.invoke(cli, ["clean", "--all"])
    assert result.exit_code == 0
    assert not blob.exists()
