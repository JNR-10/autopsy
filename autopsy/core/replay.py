"""ReplayEngine - re-execute (or simulate replay of) an agent from a bundle.

For the hackathon demo, we provide TWO modes:

1. **Simulated replay** (always works, no module reload):
   Given a TraceBundle dict and a "fix" applied at a target node, we synthesize
   a plausible replay trace by mocking the failing node with a success result.
   This is fast, deterministic, and shows the dashboard pipeline visually
   "going green".

2. **Live replay** (requires the original module to be importable):
   Loads the agent function via importlib, sets contextvars so the @lens.trace
   decorator returns frozen outputs for pre-checkpoint nodes, and re-runs from
   the target node. This is the full vision but more fragile.

The CLI defaults to simulated replay for safety; pass --live to use live mode.
"""
from __future__ import annotations

import contextvars
import importlib.util
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("autopsy.replay")

_REPLAY_MODE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_REPLAY_MODE", default=False)
_REPLAY_OUTPUTS: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_REPLAY_OUTPUTS", default={})


class ReplayEngine:
    def __init__(self, bundle: dict[str, Any]):
        self.bundle = bundle

    def simulated_replay(
        self,
        target_node_id: str,
        fix_description: str = "Fix applied",
    ) -> dict:
        """Return a synthetic comparison without actually re-running anything."""
        original_events = self.bundle["events"]
        new_session_id = f"replay:{self.bundle['session_id'][:8]}:{target_node_id[:6]}"

        replay_events: list[dict] = []

        node_index = self.bundle.get("node_index") or {}
        node_info = node_index.get(target_node_id, {})
        target_name = (
            (node_info.get("start_event") or {}).get("node_name") or "target")

        ts = time.time()

        replay_events.append({
            "event_type": "session_start",
            "session_id": new_session_id,
            "timestamp": ts,
            "agent_name": f"{self.bundle.get('agent_name', '')} (replay)",
            "input_query": self.bundle.get("input_query", ""),
            "metadata": {"replay_of": self.bundle["session_id"],
                         "target_node_id": target_node_id,
                         "fix": fix_description},
        })

        total_dur = 0.0
        node_count = 0

        seen_nodes: set[str] = set()
        for ev in original_events:
            if ev.get("event_type") != "node_start":
                continue
            nid = ev.get("node_id")
            if not nid or nid in seen_nodes:
                continue
            seen_nodes.add(nid)
            node_count += 1
            replay_events.append({**ev, "session_id": new_session_id,
                                  "timestamp": ts})
            orig_end = (node_index.get(nid) or {}).get("end_event")
            orig_err = (node_index.get(nid) or {}).get("error_event")
            orig_dur = ((orig_end or {}).get("duration_ms")
                        or (orig_err or {}).get("duration_ms") or 50.0)
            replay_dur = orig_dur * 0.7
            total_dur += replay_dur
            output_data: Any
            if orig_end is not None:
                output_data = orig_end.get("output_data")
            else:
                output_data = {
                    "__replayed_success": True,
                    "node_name": ev.get("node_name", ""),
                    "fix": fix_description,
                }
            replay_events.append({
                "event_type": "node_end",
                "session_id": new_session_id,
                "node_id": nid,
                "timestamp": ts,
                "duration_ms": replay_dur,
                "output_data": output_data,
                "output_hash": "replay",
            })

        total_tokens_orig = sum(
            int(e.get("total_tokens") or 0)
            for e in original_events if e.get("event_type") == "llm_response"
        )
        total_tokens_replay = int(total_tokens_orig * 0.75)

        summary = self.bundle.get("summary") or {}
        replay_events.append({
            "event_type": "session_end",
            "session_id": new_session_id,
            "timestamp": ts,
            "total_duration_ms": total_dur,
            "total_tokens": total_tokens_replay,
            "total_cost_usd": 0.0,
            "node_count": node_count,
            "error_count": 0,
            "status": "success",
        })

        orig_dur_total = summary.get("total_duration_ms", 0) or 0

        return {
            "session_id": new_session_id,
            "original_session_id": self.bundle["session_id"],
            "target_node_id": target_node_id,
            "target_node_name": target_name,
            "fix_description": fix_description,
            "events": replay_events,
            "dag_edges": self.bundle.get("dag_edges") or [],
            "summary": {
                "status": "success",
                "node_count": node_count,
                "error_count": 0,
                "total_duration_ms": total_dur,
                "total_tokens": total_tokens_replay,
            },
            "comparison": {
                "latency_delta_ms": total_dur - orig_dur_total,
                "token_delta": total_tokens_replay - total_tokens_orig,
                "errors_fixed": int(summary.get("error_count", 0)),
                "original": {
                    "duration_ms": orig_dur_total,
                    "tokens": total_tokens_orig,
                    "errors": summary.get("error_count", 0),
                    "status": summary.get("status", "unknown"),
                },
                "replay": {
                    "duration_ms": total_dur,
                    "tokens": total_tokens_replay,
                    "errors": 0,
                    "status": "success",
                },
            },
            "side_effect_warning": (
                "Simulated replay - no real LLM/tool calls were made. "
                "For live replay, use 'autopsy replay --live'."
            ),
        }

    async def live_replay_from_node(
        self,
        target_node_id: str,
        model_override: Optional[str] = None,
        prompt_patch: Optional[str] = None,
    ) -> dict:
        """Re-import the agent module and run it; mocks pre-checkpoint outputs."""
        frozen_node_ids = self._nodes_before(target_node_id)
        checkpoints = self.bundle.get("replay_checkpoints") or {}
        frozen_outputs = {
            nid: checkpoints.get(nid, "null")
            for nid in frozen_node_ids
        }

        mode_token = _REPLAY_MODE.set(True)
        out_token = _REPLAY_OUTPUTS.set(frozen_outputs)
        try:
            module_path = self.bundle.get("agent_module_path", "")
            fn_qualname = self.bundle.get("agent_fn_name", "")
            if not module_path or not Path(module_path).exists():
                raise FileNotFoundError(
                    f"Original agent module not found at {module_path!r}. "
                    "Run simulated replay instead.")
            mod_name = "_autopsy_replay_" + Path(module_path).stem
            spec = importlib.util.spec_from_file_location(mod_name, module_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load module spec for {module_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            attr = fn_qualname.split(".")[-1]
            fn = getattr(module, attr, None)
            if fn is None:
                raise AttributeError(f"Function {attr!r} not found in module")
            result = await fn(self.bundle.get("input_query", ""))
            return {"status": "success", "result": result}
        finally:
            try:
                _REPLAY_MODE.reset(mode_token)
                _REPLAY_OUTPUTS.reset(out_token)
            except Exception:
                pass

    def _nodes_before(self, target_node_id: str) -> list[str]:
        """Return node_ids that appear before target in execution order."""
        order: list[str] = []
        for ev in self.bundle["events"]:
            if ev.get("event_type") != "node_start":
                continue
            nid = ev.get("node_id")
            if nid == target_node_id:
                break
            if nid and nid not in order:
                order.append(nid)
        return order
