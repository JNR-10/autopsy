"""Session-end detector evaluation must stay under 2 ms p99."""
from __future__ import annotations

from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent
from autopsy.detectors.registry import resolve_enabled
from autopsy.detectors.runner import run_detectors

from tests.perf.harness import measure_overhead_ms


def test_run_detectors_p99_under_2ms():
    cfg = LensConfig()
    events = [
        LogEvent(
            event_id=f"01HXY0000000000000000000{i:02d}",
            parent_id=None, session_id="s", trace_id="s",
            timestamp_ns=i, kind=EventKind.LOG, name=str(i),
        )
        for i in range(100)
    ]
    dets = resolve_enabled(cfg)

    def run():
        run_detectors(
            events=events, outcome="ok", session_id="s", trace_id="s",
            parent_id=None, detectors=dets,
        )

    out = measure_overhead_ms(baseline=lambda: None, traced=run, iterations=200, warmup=20)
    assert out["p99"] < 2.0, out
