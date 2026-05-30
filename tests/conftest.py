"""Pytest config: each test uses a fresh temp session dir."""
import tempfile
import time

import pytest

import autopsy.core.session as _session


def _shutdown_writer() -> None:
    w = _session._writer_singleton
    if w is None:
        return
    try:
        w.shutdown(timeout=2.0)
    except Exception:
        pass
    deadline = time.monotonic() + 2.0
    while w.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    _session._writer_singleton = None


@pytest.fixture(autouse=True)
def autopsy_temp_session_dir(monkeypatch):
    _shutdown_writer()
    tmp = tempfile.mkdtemp(prefix="autopsy_pytest_")
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", tmp)
    yield tmp
    _shutdown_writer()
