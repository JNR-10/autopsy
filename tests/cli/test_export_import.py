"""Tests for autopsy export/import commands."""
from __future__ import annotations

import json
import tarfile

import pytest

from autopsy.cli.main import cli


@pytest.fixture(autouse=True)
def cli_autopsy_root(session_root, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(session_root))


def test_export_tar_creates_archive(cli_runner, writer_session_ok, tmp_path):
    out = tmp_path / "export.tar.gz"
    result = cli_runner.invoke(cli, ["export", "--out", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert any(n.startswith("sessions/") for n in names)


def test_export_json_legacy_format(cli_runner, writer_session_ok, tmp_path):
    out = tmp_path / "export.json"
    result = cli_runner.invoke(cli, ["export", "--out", str(out), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(out.read_text())
    assert data["version"] == "1"
    assert len(data["sessions"]) >= 1


def test_import_tar_round_trip(cli_runner, writer_session_ok, tmp_path, monkeypatch):
    out = tmp_path / "export.tar.gz"
    export = cli_runner.invoke(cli, ["export", "--out", str(out)])
    assert export.exit_code == 0

    import_root = tmp_path / "imported"
    import_root.mkdir()
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(import_root))

    result = cli_runner.invoke(cli, ["import", str(out)])
    assert result.exit_code == 0
    ls = cli_runner.invoke(cli, ["ls", "--json"])
    rows = json.loads(ls.output)
    assert any(r["session_id"] == writer_session_ok for r in rows)


def test_deploy_shows_deprecation_warning(cli_runner, writer_session_ok, tmp_path):
    out = tmp_path / "legacy.json"
    result = cli_runner.invoke(cli, ["deploy", "--out", str(out)])
    assert result.exit_code == 0
    assert "deprecated" in result.output.lower()
    assert out.exists()
