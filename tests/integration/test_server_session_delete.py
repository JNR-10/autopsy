"""Tests for server session delete helpers and endpoints."""
from __future__ import annotations

import httpx
import pytest

from autopsy.core.events import Manifest
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.server.app import create_app
from autopsy.server.sessions import is_live_session_row


def test_is_live_session_row():
    assert is_live_session_row({"status": "live"})
    assert is_live_session_row({"summary": {"status": "running"}})
    assert not is_live_session_row({"status": "ok"})
    assert not is_live_session_row({"status": "error"})


@pytest.fixture
def store_with_sessions(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    for sid, status in [("live-sid", "live"), ("done-sid", "ok")]:
        sd = store._session_dir(sid)
        sd.mkdir(parents=True)
        manifest = Manifest(
            session_id=sid,
            agent_name="test",
            start_time_ns=1,
            status=status,
            autopsy_version="0.2.0",
            wall_clock_ns_at_start=1,
            monotonic_ns_at_start=1,
        )
        (sd / "manifest.json").write_text(manifest.model_dump_json(indent=2))
        store.index.upsert(manifest, str(sd))
    return store


@pytest.mark.asyncio
async def test_delete_all_sessions_v1_keep_live(store_with_sessions, monkeypatch):
    store = store_with_sessions
    monkeypatch.setattr("autopsy.server.app.filesystem_store", lambda: store)
    monkeypatch.setattr("autopsy.server.app._session_dir", lambda: store.root / "sessions")

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/sessions?keep_live=1")
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
    assert (store.root / "sessions" / "live-sid").exists()
    assert not (store.root / "sessions" / "done-sid").exists()


@pytest.mark.asyncio
async def test_delete_session_v1(store_with_sessions, monkeypatch):
    store = store_with_sessions
    monkeypatch.setattr("autopsy.server.app.filesystem_store", lambda: store)
    monkeypatch.setattr("autopsy.server.app._session_dir", lambda: store.root / "sessions")

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.delete("/api/sessions/done-sid")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert not (store.root / "sessions" / "done-sid").exists()
