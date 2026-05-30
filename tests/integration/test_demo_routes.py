"""Demo routes are gated behind AUTOPSY_DEMO=1."""
from __future__ import annotations

import httpx
import pytest

from autopsy.server.app import create_app


@pytest.mark.asyncio
async def test_demo_routes_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUTOPSY_DEMO", raising=False)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/demo/status")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_demo_routes_enabled_when_flag_set(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DEMO", "1")
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/demo/status")
    assert r.status_code == 200
    assert r.json()["fix_applied"] is False
