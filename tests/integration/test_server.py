"""Integration tests for FastAPI server using httpx in-process."""

import time

import httpx
import pytest

from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.session import get_writer
from autopsy.server.app import create_app


@pytest.fixture
def lens_with_tmp_store(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path
    get_writer(cfg).shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _latest_session_id(tmp_path) -> str:
    reader = LegacyBundleReader(root=tmp_path)
    deadline = time.monotonic() + 2.0
    rows = []
    while time.monotonic() < deadline:
        rows = reader.list()
        if rows:
            break
        time.sleep(0.02)
    assert rows, "expected at least one session on disk"
    return rows[0]["session_id"]


@pytest.mark.asyncio
async def test_health_endpoint():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                  base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_sessions_empty_initially():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                  base_url="http://test") as c:
        r = await c.get("/api/sessions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_unknown_session_returns_404():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                  base_url="http://test") as c:
        r = await c.get("/api/sessions/nonexistent")
        assert r.status_code == 404
        r = await c.post("/api/sessions/nonexistent/diagnose", json={})
        assert r.status_code == 404
        r = await c.post("/api/sessions/nonexistent/replay",
                         json={"node_id": "x"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_full_diagnose_replay_flow(lens_with_tmp_store, monkeypatch):
    lens, tmp_path = lens_with_tmp_store
    monkeypatch.setattr(
        "autopsy.server.app._bundle_reader",
        lambda: LegacyBundleReader(root=tmp_path),
    )

    @lens.trace(name="bad")
    async def bad():
        raise ValueError("oops")

    with pytest.raises(ValueError):
        await bad()

    sid = _latest_session_id(tmp_path)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                  base_url="http://test") as c:
        r = await c.get(f"/api/sessions/{sid}")
        assert r.status_code == 200
        bundle = r.json()
        assert bundle["session_id"] == sid

        r = await c.get(f"/api/sessions/{sid}/dag")
        assert r.status_code == 200
        assert "nodes" in r.json()

        # Diagnose with no API key -> heuristic fallback (must not crash).
        r = await c.post(f"/api/sessions/{sid}/diagnose", json={})
        assert r.status_code == 200
        diag = r.json()
        assert "root_cause" in diag

        # Find a node id to replay (from node_index or events).
        bundle_resp = bundle
        if bundle_resp.get("node_index"):
            first_node = next(iter(bundle_resp["node_index"].keys()))
        else:
            first_node = next(
                e["node_id"] for e in bundle_resp["events"]
                if e.get("event_type") == "node_start" and e.get("node_id")
            )
        r = await c.post(f"/api/sessions/{sid}/replay",
                          json={"node_id": first_node, "fix_description": "fix"})
        assert r.status_code == 200
        result = r.json()
        assert result["summary"]["status"] == "success"
