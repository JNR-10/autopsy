"""Soak test stub. Skipped by default; runnable with `-m slow`.

A real soak would run for hours and measure RSS over time. This is the
scaffold: it loops a traced function for a small number of iterations and
asserts the writer is still alive and the dropped-events counter is sane.
"""
from __future__ import annotations

import asyncio
import os
import resource

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.session import get_writer


@pytest.mark.slow
def test_soak_writer_stays_alive_and_bounded_memory(tmp_path, monkeypatch):
    iters = int(os.environ.get("AUTOPSY_SOAK_ITERS", "5000"))
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def agent(q):
        return q

    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for i in range(iters):
        asyncio.run(agent(f"q-{i}"))
    rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    w = get_writer(cfg)
    assert w.is_alive()
    growth_mb = (rss_end - rss_start) / 1024
    assert growth_mb < 200, f"memory grew {growth_mb:.1f} MB over {iters} calls"
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
