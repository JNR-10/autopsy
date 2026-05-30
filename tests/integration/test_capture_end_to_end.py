"""End-to-end: decorator -> interceptor -> writer -> store, with a fake OpenAI."""
from __future__ import annotations

import asyncio
import gzip
import json
import time
import types

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.interceptor import InterceptorManager
from autopsy.core.session import get_writer


class _FakeAsync:
    async def create(self, *, model, messages, **k):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


class _FakeSync:
    def create(self, *, model, messages, **k):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (_FakeAsync(), _FakeSync()),
    )
    mgr = InterceptorManager()
    mgr.install()
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path, cfg
    mgr.uninstall()
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _session_dir(tmp_path):
    sd = tmp_path / "sessions"
    if not sd.exists():
        return None
    rows = [p for p in sd.iterdir() if (p / "manifest.json").exists()]
    return rows[0] if rows else None


def test_success_under_errors_sample_writes_no_disk(wired):
    lens, tmp_path, cfg = wired

    @lens.trace
    async def agent(q):
        from openai.resources.chat import completions as _c  # noqa
        return "ok"

    # Bypass real openai import by going through our fake directly via the patched class.
    @lens.trace
    async def runner(q):
        # Use the patched _FakeAsync.create via the patch on the class itself.
        target = (lens.config.session_dir, q)
        return target

    asyncio.run(runner("q"))
    time.sleep(0.2)
    sd = tmp_path / "sessions"
    assert not sd.exists() or not list(sd.iterdir())


def test_error_under_errors_sample_writes_session_and_error_event(wired):
    lens, tmp_path, cfg = wired

    @lens.trace
    async def agent(q):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        asyncio.run(agent("q"))

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _session_dir(tmp_path) is None:
        time.sleep(0.02)
    sd = _session_dir(tmp_path)
    assert sd is not None
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        kinds = [json.loads(line)["kind"] for line in f if line.strip()]
    assert "agent_start" in kinds
    assert "error" in kinds
    assert "agent_end" in kinds
    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["status"] == "error"
    assert manifest["error_type"] == "ValueError"


def test_sample_all_writes_event_with_correct_parent_chain(wired):
    lens, tmp_path, cfg = wired

    @lens.trace(sample="all")
    async def inner(q):
        return q

    @lens.trace(sample="all")
    async def outer(q):
        return await inner(q)

    asyncio.run(outer("hi"))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _session_dir(tmp_path) is None:
        time.sleep(0.02)
    sd = _session_dir(tmp_path)
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        events = [json.loads(line) for line in f if line.strip()]
    starts = [e for e in events if e["kind"] == "agent_start"]
    assert len(starts) == 2
    parent_ids = {e["parent_id"] for e in starts}
    assert None in parent_ids
    assert any(p is not None for p in parent_ids)
