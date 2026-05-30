"""Smoke test for the perf harness — measure overhead of a no-op decorator."""
from __future__ import annotations

from tests.perf.harness import measure_async_overhead_ms, measure_overhead_ms


def test_async_harness_returns_percentile_dict():
    async def noop():
        return None

    out = measure_async_overhead_ms(
        baseline=noop, traced=noop, iterations=100,
    )
    assert {"p50", "p95", "p99", "mean", "iterations"} <= set(out)
    assert out["iterations"] == 100
    assert out["p99"] >= out["p50"]


def test_harness_returns_percentile_dict():
    out = measure_overhead_ms(
        baseline=lambda: None,
        traced=lambda: None,
        iterations=100,
    )
    assert {"p50", "p95", "p99", "mean", "iterations"} <= set(out)
    assert out["iterations"] == 100
    assert out["p99"] >= out["p50"]
