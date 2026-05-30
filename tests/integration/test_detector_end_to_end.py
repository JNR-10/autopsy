"""End-to-end: semantic failure detection promotes session under sample=errors."""
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


class _FakeEmptyAsync:
    async def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(
                prompt_tokens=1, completion_tokens=0, total_tokens=1,
            ),
        )


class _FakeEmptySync:
    def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(
                prompt_tokens=1, completion_tokens=0, total_tokens=1,
            ),
        )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    fake_async = _FakeEmptyAsync()
    fake_sync = _FakeEmptySync()
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (fake_async, fake_sync),
    )
    mgr = InterceptorManager()
    mgr.install()
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path, cfg, fake_async
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


def test_semantic_failure_empty_llm_response_keeps_session(wired):
    """Empty LLM content under errors sampling triggers detector_verdict + status=error."""
    lens, tmp_path, cfg, fake_async = wired

    @lens.trace
    async def agent(q):
        await fake_async.create(
            model="gpt-test", messages=[{"role": "user", "content": q}],
        )
        return ""

    asyncio.run(agent("hi"))

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _session_dir(tmp_path) is None:
        time.sleep(0.02)
    sd = _session_dir(tmp_path)
    assert sd is not None

    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        events = [json.loads(line) for line in f if line.strip()]
    kinds = [e["kind"] for e in events]
    assert "llm_response" in kinds
    assert "detector_verdict" in kinds

    verdicts = [e for e in events if e["kind"] == "detector_verdict"]
    assert any(v["verdict"] == "fail" for v in verdicts)
    assert any(v["detector_name"] == "empty_response" for v in verdicts)

    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["status"] == "error"
    assert manifest["error_type"] == "detector:empty_response"
