"""Tests for the LoggingExporter that emits the finalization log line."""
from __future__ import annotations

import logging

from autopsy.core.events import Manifest
from autopsy.core.exporters.logging import LoggingExporter


def _manifest(*, status="ok", agent_name="a", error_type=None):
    return Manifest(
        session_id="01HXY000000000000000000001",
        agent_name=agent_name,
        start_time_ns=1,
        end_time_ns=1_000_000,
        duration_ms=1.0,
        status=status,
        error_type=error_type,
        event_count=3,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=1,
        monotonic_ns_at_start=1,
    )


def test_finalize_emits_warning_for_error(caplog):
    exp = LoggingExporter(info_rate_s=60)
    with caplog.at_level(logging.WARNING, logger="autopsy"):
        exp.finalize_session(_manifest(status="error", error_type="ValueError"))
    recs = [r for r in caplog.records if r.name == "autopsy"]
    assert any(r.levelno == logging.WARNING for r in recs)
    rec = next(r for r in recs if r.levelno == logging.WARNING)
    assert getattr(rec, "session_id", None) == "01HXY000000000000000000001"
    assert getattr(rec, "status", None) == "error"
    assert getattr(rec, "error_type", None) == "ValueError"


def test_finalize_emits_info_for_ok(caplog):
    exp = LoggingExporter(info_rate_s=0)
    with caplog.at_level(logging.INFO, logger="autopsy"):
        exp.finalize_session(_manifest(status="ok"))
    recs = [r for r in caplog.records if r.name == "autopsy" and r.levelno == logging.INFO]
    assert recs


def test_info_logs_are_rate_limited_per_agent(caplog):
    exp = LoggingExporter(info_rate_s=60)
    with caplog.at_level(logging.INFO, logger="autopsy"):
        exp.finalize_session(_manifest(status="ok", agent_name="a"))
        exp.finalize_session(_manifest(status="ok", agent_name="a"))
    recs = [r for r in caplog.records if r.name == "autopsy" and r.levelno == logging.INFO]
    assert len(recs) == 1


def test_disabled_skip_all(caplog):
    exp = LoggingExporter(enabled=False)
    with caplog.at_level(logging.WARNING, logger="autopsy"):
        exp.finalize_session(_manifest(status="error"))
    assert not [r for r in caplog.records if r.name == "autopsy"]


def test_export_is_a_noop(tmp_path):
    exp = LoggingExporter()
    exp.export("01HXY000000000000000000001", [])
