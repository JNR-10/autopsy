"""Tiny perf harness for measuring decorator overhead.

Runs `baseline` and `traced` callables alternately to amortize warmup and
CPU frequency scaling effects. Returns dict of percentile durations in ms.
"""
from __future__ import annotations

import statistics
import time
from typing import Callable


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
    overheads.sort()
    return {
        "p50": _percentile(overheads, 50),
        "p95": _percentile(overheads, 95),
        "p99": _percentile(overheads, 99),
        "mean": statistics.fmean(overheads) if overheads else 0.0,
        "iterations": iterations,
    }
