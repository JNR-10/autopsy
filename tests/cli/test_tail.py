"""Tests for autopsy tail command."""
from __future__ import annotations

import json
import time

import pytest

from autopsy.cli.main import cli
from autopsy.core.events import Manifest


@pytest.fixture(autouse=True)
def cli_autopsy_root(session_root, monkeypatch):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(session_root))


def test_tail_finalized_last_n_lines(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["tail", writer_session_ok, "--lines", "1"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.strip().split("\n") if ln]
    assert len(lines) == 1


def test_tail_finalized_json_ndjson(cli_runner, writer_session_ok):
    result = cli_runner.invoke(cli, ["tail", writer_session_ok, "--json", "--lines", "2"])
    assert result.exit_code == 0
    rows = [json.loads(ln) for ln in result.output.strip().split("\n") if ln]
    assert len(rows) >= 1
    assert all(isinstance(r, dict) for r in rows)


def test_tail_not_found(cli_runner):
    result = cli_runner.invoke(cli, ["tail", "missing-session-id"])
    assert result.exit_code != 0


def test_tail_live_polls_new_events(session_root, bundle_reader):
    import io
    import threading

    from autopsy.cli.tail import tail_session

    sid = "01HXY00000000000000000000L"
    sd = session_root / "sessions" / sid
    sd.mkdir(parents=True)
    (sd / "artifacts").mkdir()
    events_path = sd / "events.jsonl"
    events_path.write_text('{"kind":"agent_start","event_id":"e1"}\n')
    live_manifest = Manifest(
        session_id=sid, agent_name="live-agent", start_time_ns=1,
        end_time_ns=None, duration_ms=None, status="live",
        error_type=None, event_count=1, dropped_events=0,
        autopsy_format_version=1, autopsy_version="0.2.0",
        wall_clock_ns_at_start=1, monotonic_ns_at_start=1,
    )
    (sd / "manifest.json").write_text(live_manifest.model_dump_json())

    def append_event():
        time.sleep(0.05)
        with events_path.open("a") as f:
            f.write('{"kind":"agent_end","event_id":"e2"}\n')

    threading.Thread(target=append_event, daemon=True).start()

    out = io.StringIO()
    tail_session(
        bundle_reader, sid,
        poll_interval_s=0.05,
        max_polls=10,
        out=out,
    )
    text = out.getvalue()
    assert "agent_start" in text
    assert "agent_end" in text
