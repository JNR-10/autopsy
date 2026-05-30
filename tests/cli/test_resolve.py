"""Tests for autopsy.cli.resolve.resolve_session_id."""
from __future__ import annotations

import json

import click
import pytest

from autopsy.cli.resolve import resolve_session_id
from autopsy.core.compat import LegacyBundleReader


def _write_v0(root, session_id: str) -> None:
    sessions = root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sessions.joinpath(f"{session_id}.json").write_text(json.dumps({
        "session_id": session_id,
        "created_at": 1700000000.0,
        "agent_name": "old",
        "input_query": "q",
        "events": [],
        "summary": {"status": "success", "error_count": 0},
    }))


def _write_v1(root, session_id: str, agent_name: str = "new") -> None:
    sd = root / "sessions" / session_id
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "manifest.json").write_text(json.dumps({
        "session_id": session_id,
        "agent_name": agent_name,
        "start_time_ns": 1,
        "status": "ok",
        "autopsy_format_version": 1,
        "autopsy_version": "0.0.0",
        "wall_clock_ns_at_start": 1,
        "monotonic_ns_at_start": 1,
    }))
    (sd / "events.jsonl").write_text("{}\n")


def test_resolve_exact_match_v1(session_root):
    sid = "01HXY000000000000000000001"
    _write_v1(session_root, sid)
    reader = LegacyBundleReader(root=session_root)
    assert resolve_session_id(reader, sid) == sid


def test_resolve_exact_match_v0(session_root):
    sid = "old-session-1"
    _write_v0(session_root, sid)
    reader = LegacyBundleReader(root=session_root)
    assert resolve_session_id(reader, sid) == sid


def test_resolve_unique_prefix(session_root):
    sid = "01HXY000000000000000000001"
    _write_v1(session_root, sid)
    reader = LegacyBundleReader(root=session_root)
    assert resolve_session_id(reader, "01HXY000000000000000000") == sid


def test_resolve_not_found(session_root):
    reader = LegacyBundleReader(root=session_root)
    with pytest.raises(click.ClickException, match="not found"):
        resolve_session_id(reader, "missing")


def test_resolve_ambiguous_prefix(session_root):
    _write_v1(session_root, "01HXY000000000000000000001")
    _write_v1(session_root, "01HXY000000000000000000002")
    reader = LegacyBundleReader(root=session_root)
    with pytest.raises(click.ClickException, match="ambiguous"):
        resolve_session_id(reader, "01HXY")


def test_resolve_writer_session_ok(bundle_reader, writer_session_ok):
    assert resolve_session_id(bundle_reader, writer_session_ok) == writer_session_ok


def test_resolve_writer_session_detector_fail_prefix(
    bundle_reader, writer_session_detector_fail,
):
    sid = writer_session_detector_fail
    assert resolve_session_id(bundle_reader, sid[:18]) == sid
