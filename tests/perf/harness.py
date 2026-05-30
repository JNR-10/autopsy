"""Tiny perf harness for measuring decorator overhead.

Runs `baseline` and `traced` callables alternately to amortize warmup and
CPU frequency scaling effects. Returns dict of percentile durations in ms.
"""
from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import Awaitable, Callable


def _percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    k = int(round((p / 100.0) * (len(sorted_values) - 1)))
    return sorted_values[k]


def measure_overhead_ms(
    *,
    baseline: Callable[[], object],
    traced: Callable[[], object],
    iterations: int = 1000,
    warmup: int = 50,
) -> dict[str, float]:
    for _ in range(warmup):
        baseline()
        traced()
    overheads: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        baseline()
        t1 = time.perf_counter_ns()
        traced()
        t2 = time.perf_counter_ns()
        overheads.append(((t2 - t1) - (t1 - t0)) / 1e6)
    return _percentile_summary(overheads, iterations)


def _percentile_summary(overheads: list[float], iterations: int) -> dict[str, float]:
    overheads.sort()
    return {
        "p50": _percentile(overheads, 50),
        "p95": _percentile(overheads, 95),
        "p99": _percentile(overheads, 99),
        "mean": statistics.fmean(overheads) if overheads else 0.0,
        "iterations": iterations,
    }


def measure_async_overhead_ms(
    *,
    baseline: Callable[[], Awaitable[object]],
    traced: Callable[[], Awaitable[object]],
    iterations: int = 1000,
    warmup: int = 50,
) -> dict[str, float]:
    """Like ``measure_overhead_ms`` but reuses one event loop for all iterations.

    Real async agents run many traced calls on a single loop; spinning up
    ``asyncio.run()`` per iteration would dominate p99 with loop lifecycle noise.
    """

    async def _run() -> list[float]:
        for _ in range(warmup):
            await baseline()
            await traced()
        overheads: list[float] = []
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            await baseline()
            t1 = time.perf_counter_ns()
            await traced()
            t2 = time.perf_counter_ns()
            overheads.append(((t2 - t1) - (t1 - t0)) / 1e6)
        return overheads

    return _percentile_summary(asyncio.run(_run()), iterations)
