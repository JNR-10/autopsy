"""Tests for the new sync+async OpenAI interceptor."""
from __future__ import annotations

import asyncio
import types


from autopsy.core.config import LensConfig
from autopsy.core.context import set_session
from autopsy.core.interceptor import InterceptorV2Manager
from autopsy.core.session import Session, get_writer
from autopsy.core.writer import SampleMode


class _FakeAsyncCompletions:
    async def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


class _FakeSyncCompletions:
    def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi-sync", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


def test_no_op_when_openai_missing(monkeypatch):
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: None,
    )
    mgr = InterceptorV2Manager()
    mgr.install()
    mgr.uninstall()


def test_async_call_emits_llm_request_response(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)

    async_target = _FakeAsyncCompletions()
    sync_target = _FakeSyncCompletions()
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (async_target, sync_target),
    )

    mgr = InterceptorV2Manager()
    mgr.install()
    try:
        s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
        token = set_session(s)
        try:
            asyncio.run(async_target.create(model="m", messages=[{"role": "u", "content": "hi"}]))
        finally:
            set_session(None, token=token)
        s.end(outcome="ok")
    finally:
        mgr.uninstall()
        writer.shutdown(timeout=2.0)
        monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    sd = tmp_path / "sessions" / s.session_id
    assert (sd / "manifest.json").exists()
    import gzip
    import json
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        kinds = [json.loads(line)["kind"] for line in f]
    assert "llm_request" in kinds
    assert "llm_response" in kinds


def test_sync_call_emits_llm_request_response(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)

    async_target = _FakeAsyncCompletions()
    sync_target = _FakeSyncCompletions()
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (async_target, sync_target),
    )

    mgr = InterceptorV2Manager()
    mgr.install()
    try:
        s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
        token = set_session(s)
        try:
            sync_target.create(model="m", messages=[{"role": "u", "content": "hi"}])
        finally:
            set_session(None, token=token)
        s.end(outcome="ok")
    finally:
        mgr.uninstall()
        writer.shutdown(timeout=2.0)
        monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    sd = tmp_path / "sessions" / s.session_id
    assert (sd / "manifest.json").exists()


def test_passthrough_when_diagnostics_call_is_set(tmp_path, monkeypatch):
    from autopsy.core.context import set_diagnostics_call

    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)

    sync_target = _FakeSyncCompletions()
    async_target = _FakeAsyncCompletions()
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (async_target, sync_target),
    )

    mgr = InterceptorV2Manager()
    mgr.install()
    try:
        s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
        token = set_session(s)
        dtok = set_diagnostics_call(True)
        try:
            sync_target.create(model="m", messages=[])
        finally:
            set_diagnostics_call(False, token=dtok)
            set_session(None, token=token)
        s.end(outcome="ok")
    finally:
        mgr.uninstall()
        writer.shutdown(timeout=2.0)
        monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    import gzip
    import json
    sd = tmp_path / "sessions" / s.session_id
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        kinds = [json.loads(line)["kind"] for line in f]
    assert "llm_request" not in kinds
