import pytest
from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
import autopsy.core.session as session_mod


@pytest.mark.asyncio
async def test_root_async_creates_session_under_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def agent():
        from autopsy.core.context import current_session
        assert current_session() is not None
        return 1

    assert await agent() == 1


def test_per_call_detectors_override(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    lens = LensDecorator(config=cfg)

    @lens.trace(detectors=[])
    def agent():
        return 1

    assert agent() == 1


def test_per_call_detector_profile_via_session_begin(tmp_path, monkeypatch):
    """Per-call overrides apply at Session.end (decorator passes same overrides)."""
    import json
    import time

    from autopsy.core.events import EventKind, LLMResponseEvent
    from autopsy.core.session import Session, get_writer
    from autopsy.detectors.overrides import DetectorCallOverrides

    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    overrides = DetectorCallOverrides(
        detector_profile="strict",
        latency_threshold_ms=1,
        promote_on_warn=True,
    )
    s = Session.begin(
        config=cfg, agent_name="a", sample="errors",
        detectors=["high_latency"], detector_overrides=overrides,
    )
    s.record_event(LLMResponseEvent(
        event_id="01HXY0000000000000000000A",
        parent_id=None, session_id=s.session_id, trace_id=s.session_id,
        timestamp_ns=1, kind=EventKind.LLM_RESPONSE, model="m",
        content="ok", latency_ms=5000.0,
    ))
    s.end(outcome="ok")
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    manifest_path = tmp_path / "sessions" / s.session_id / "manifest.json"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not manifest_path.exists():
        time.sleep(0.02)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest.get("error_type") == "detector_warn:high_latency"
