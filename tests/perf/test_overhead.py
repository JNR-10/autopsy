"""p99 overhead per traced call must stay under 5 ms (spec target)."""
from __future__ import annotations

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.session import get_writer

from tests.perf.harness import measure_async_overhead_ms, measure_overhead_ms


@pytest.mark.slow
def test_async_p99_overhead_under_5ms(tmp_path, monkeypatch):
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        enabled_detectors=[],
    )
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def traced_agent():
        return 1

    async def baseline_agent():
        return 1

    out = measure_async_overhead_ms(
        baseline=baseline_agent,
        traced=traced_agent,
        iterations=500,
        warmup=50,
    )
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    assert out["p99"] < 5.0, f"p99 overhead {out['p99']:.2f} ms exceeds 5ms target ({out})"


@pytest.mark.slow
def test_sync_p99_overhead_under_5ms(tmp_path, monkeypatch):
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        enabled_detectors=[],
    )
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    def traced_agent():
        return 1

    def baseline_agent():
        return 1

    out = measure_overhead_ms(
        baseline=baseline_agent, traced=traced_agent, iterations=2000, warmup=100,
    )
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    assert out["p99"] < 5.0, f"sync p99 overhead {out['p99']:.2f} ms exceeds 5ms target ({out})"
