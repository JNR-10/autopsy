"""Tests for the public autopsy.log breadcrumb API."""
from __future__ import annotations



from autopsy import log
from autopsy.core.config import LensConfig
from autopsy.core.context import set_session
from autopsy.core.session import Session, get_writer
from autopsy.core.writer import SampleMode


def test_log_outside_session_is_a_noop():
    log("no_session_here", k=1)


def test_log_attaches_log_event_to_current_session(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)
    s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
    token = set_session(s)
    try:
        log("retry_attempt", attempt=3, reason="rate_limited")
        log("plain")
    finally:
        set_session(None, token=token)
    s.end(outcome="ok")
    writer.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    import gzip
    import json
    sd = tmp_path / "sessions" / s.session_id
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        events = [json.loads(line) for line in f if line.strip()]
    logs = [e for e in events if e["kind"] == "log"]
    assert any(e.get("name") == "retry_attempt" and e["attributes"]["attempt"] == 3 for e in logs)
    assert any(e.get("name") == "plain" for e in logs)


def test_log_never_raises_on_bad_inputs():
    log(123, weird=object())  # type: ignore[arg-type]
