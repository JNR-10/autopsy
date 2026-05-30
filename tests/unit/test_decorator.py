"""Tests for the new @lens.trace decorator wired through the writer."""
from __future__ import annotations

import asyncio
import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.session import get_writer


@pytest.fixture
def lens_with_tmp_store(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _sessions(tmp_path):
    sd = tmp_path / "sessions"
    if not sd.exists():
        return []
    return [p.name for p in sd.iterdir() if p.is_dir() and (p / "manifest.json").exists()]


def test_async_success_with_sample_all_writes_session(lens_with_tmp_store):
    lens, tmp_path = lens_with_tmp_store

    @lens.trace
    async def agent(q):
        return q + "!"

    out = asyncio.run(agent("hi"))
    assert out == "hi!"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not _sessions(tmp_path):
        time.sleep(0.02)
    assert len(_sessions(tmp_path)) == 1


def test_async_error_writes_session_under_errors_sampling(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def agent(q):
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        asyncio.run(agent("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    rows = [p for p in sd.iterdir() if (p / "manifest.json").exists()] if sd.exists() else []
    assert len(rows) == 1


def test_async_success_writes_nothing_under_errors_sampling(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def agent(q):
        return "ok"

    asyncio.run(agent("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    assert not sd.exists() or not list(sd.iterdir())


def test_sync_function_does_not_call_asyncio_run(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    def agent(q):
        return q.upper()

    real_run = asyncio.run
    called = {"n": 0}

    def fake_run(*a, **k):
        called["n"] += 1
        return real_run(*a, **k)

    monkeypatch.setattr(asyncio, "run", fake_run)
    out = agent("hi")
    assert out == "HI"
    assert called["n"] == 0
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def test_sample_off_is_a_noop(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path))
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace(sample="off")
    async def agent(q):
        return q

    asyncio.run(agent("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    assert not sd.exists() or not list(sd.iterdir())


def test_nested_decorated_calls_share_one_session(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def inner(q):
        return q

    @lens.trace
    async def outer(q):
        return await inner(q)

    asyncio.run(outer("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    rows = [p for p in sd.iterdir() if (p / "manifest.json").exists()]
    assert len(rows) == 1
