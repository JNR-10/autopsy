"""Unit tests for ReplayEngine."""
import time

import pytest

from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.replay import ReplayEngine
from autopsy.core.session import get_writer


def _load_latest_bundle(tmp_path) -> dict:
    reader = LegacyBundleReader(root=tmp_path)
    deadline = time.monotonic() + 2.0
    rows = []
    while time.monotonic() < deadline:
        rows = reader.list()
        if rows:
            break
        time.sleep(0.02)
    assert rows, "expected at least one session on disk"
    bundle = reader.load(rows[0]["session_id"])
    assert bundle is not None
    return bundle


@pytest.fixture
def lens_with_tmp_store(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)
    yield lens, tmp_path
    get_writer(cfg).shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


@pytest.mark.asyncio
async def test_simulated_replay_fixes_errors(lens_with_tmp_store):
    lens, tmp_path = lens_with_tmp_store

    @lens.trace(name="will-fail")
    async def will_fail():
        raise RuntimeError("bad")

    @lens.trace(name="root")
    async def root():
        return await will_fail()

    with pytest.raises(RuntimeError):
        await root()

    bundle = _load_latest_bundle(tmp_path)
    # Find the failed node
    err_node_id = None
    for e in bundle["events"]:
        if e["event_type"] == "node_error":
            err_node_id = e["node_id"]
            break
    assert err_node_id is not None

    engine = ReplayEngine(bundle)
    result = engine.simulated_replay(err_node_id, "fixed")
    assert result["summary"]["status"] == "success"
    assert result["summary"]["error_count"] == 0
    assert result["comparison"]["errors_fixed"] >= 1
    orig_ms = result["comparison"]["original"]["duration_ms"]
    if orig_ms > result["comparison"]["replay"]["duration_ms"]:
        assert result["comparison"]["latency_delta_ms"] < 0


def test_simulated_replay_works_without_errors():
    # Empty/no-error bundle still produces a valid replay output.
    b = {
        "session_id": "x",
        "events": [
            {"event_type": "node_start", "node_id": "a", "node_name": "n",
             "depth": 0, "node_type": "agent"},
        ],
        "node_index": {"a": {"start_event": {"node_name": "n"}}},
        "dag_edges": [],
        "replay_checkpoints": {},
        "summary": {},
        "agent_name": "",
        "input_query": "",
        "agent_module_path": "",
        "agent_fn_name": "",
        "created_at": 0.0,
    }
    engine = ReplayEngine(b)
    r = engine.simulated_replay("a", "test")
    assert r["target_node_id"] == "a"
    assert r["summary"]["status"] == "success"
