import time

import autopsy.core.session as session_mod
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LLMResponseEvent
from autopsy.core.session import Session, get_writer

SID = "01HXY000000000000000000001"


def test_detector_fail_promotes_session_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    s = Session.begin(config=cfg, agent_name="a", sample="errors")
    s.record_event(LLMResponseEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None, session_id=s.session_id, trace_id=s.session_id,
        timestamp_ns=1, kind=EventKind.LLM_RESPONSE, model="m", content="  ",
    ))
    s.end(outcome="ok")
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    manifest = tmp_path / "sessions" / s.session_id / "manifest.json"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if manifest.exists():
            break
        time.sleep(0.02)
    assert manifest.exists()


def test_clean_session_no_disk_under_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    s = Session.begin(config=cfg, agent_name="a", sample="errors")
    s.end(outcome="ok")
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    assert not (tmp_path / "sessions").exists() or list((tmp_path / "sessions").iterdir()) == []
