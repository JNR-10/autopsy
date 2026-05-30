"""Ensure perf measurements start with no background writer activity."""
from __future__ import annotations

import time

import pytest

import autopsy.core.session as _session


@pytest.fixture(autouse=True)
def _quiesce_before_perf():
    w = _session._writer_singleton
    if w is not None:
        try:
            w.shutdown(timeout=2.0)
        except Exception:
            pass
        deadline = time.monotonic() + 2.0
        while w.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        _session._writer_singleton = None
    yield
