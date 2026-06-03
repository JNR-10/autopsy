"""Session — the per-call object the decorator creates and the interceptor reads.

Replaces the old `TraceSession`. Key differences:
- No asyncio.Queue, no drain task. Events go straight to the process-wide
  Writer daemon via `Writer.enqueue`, which is a non-blocking put_nowait.
- The session itself is cheap: an ID, a config snapshot, the writer ref,
  and a few timing fields. It does not own a thread, does not touch disk.
- The Writer is a process-wide singleton fetched via `get_writer(config)`.

A Session is created at the root @lens.trace call and is the value stored
in the `current_session` ContextVar for the lifetime of that call.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from typing import Any, Optional

from .config import LensConfig
from .events import BaseEvent, EventKind
from .store.local_fs import LocalFilesystemStore
from .ulid import new_ulid
from .writer import SampleMode, Writer

logger = logging.getLogger("autopsy.session")

_DETECTOR_RING_KINDS = frozenset({
    EventKind.LLM_REQUEST,
    EventKind.LLM_RESPONSE,
    EventKind.TOOL_CALL_START,
    EventKind.TOOL_CALL_END,
    EventKind.ERROR,
    EventKind.AGENT_END,
    EventKind.AGENT_START,
})

_writer_lock = threading.Lock()
_writer_singleton: Optional[Writer] = None


def get_writer(config: LensConfig) -> Writer:
    global _writer_singleton
    with _writer_lock:
        if _writer_singleton is None:
            root = config.session_dir or _pick_default_root()
            store = LocalFilesystemStore(root=root)
            _writer_singleton = Writer(config=config, store=store)
            _writer_singleton.start()
        return _writer_singleton


def _pick_default_root() -> str:
    import os
    import tempfile
    from pathlib import Path

    candidates = []
    raw = os.environ.get("AUTOPSY_SESSION_DIR")
    if raw:
        candidates.append(Path(os.path.expanduser(raw)))
    candidates.append(Path(os.path.expanduser("~/.autopsy")))
    candidates.append(Path.cwd() / ".autopsy")
    candidates.append(Path(tempfile.gettempdir()) / "autopsy")
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            probe = c / ".write_probe"
            probe.write_text("")
            probe.unlink(missing_ok=True)
            return str(c)
        except Exception:
            continue
    return str(candidates[-1])


def _resolve_sample(raw, config_default) -> tuple[SampleMode, bool]:
    """Return (mode, head_keep) given a per-call sample arg + the config default.

    head_keep is True iff a head-based rate roll selected this call.
    """
    chosen = raw if raw is not None else config_default
    if chosen == "all":
        return SampleMode.ALL, False
    if chosen == "off":
        return SampleMode.OFF, False
    if chosen == "errors":
        return SampleMode.ERRORS, False
    try:
        f = float(chosen)
    except (TypeError, ValueError):
        return SampleMode.ERRORS, False
    if random.random() < f:
        return SampleMode.RATE, True
    return SampleMode.ERRORS, False


class Session:
    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str,
        sample: SampleMode,
        head_keep: bool,
        writer: Writer | None,
        config: LensConfig,
        start_perf_ns: int,
        wall_ns: int,
    ):
        self.session_id = session_id
        self.agent_name = agent_name
        self.sample = sample
        self.head_keep = head_keep
        self.writer = writer
        self._config = config
        self.start_perf_ns = start_perf_ns
        self._wall_ns = wall_ns
        self._capture: deque[BaseEvent] = deque()
        self._capture_bytes: int = 0
        self._detector_ring: deque[BaseEvent] = deque()
        self._detectors: list[str] | None = None
        self._detector_overrides: Any | None = None

    def capture_events(self) -> list[BaseEvent]:
        return list(self._capture)

    def events_for_detectors(self) -> list[BaseEvent]:
        """Merge detector ring, capture, flushed writer history, and on-disk tail."""
        from pathlib import Path

        from autopsy.core.compat import load_v1_base_events

        seen: dict[str, BaseEvent] = {ev.event_id: ev for ev in self._detector_ring}
        for ev in self._capture:
            seen.setdefault(ev.event_id, ev)
        w = self.writer
        if w is not None and self._config.detector_full_trace:
            w.flush_session_now(self.session_id)
            for ev in w.accumulated_events_for_session(self.session_id):
                seen[ev.event_id] = ev
        elif w is not None:
            for ev in w.snapshot_events_for_detectors(self.session_id):
                seen.setdefault(ev.event_id, ev)
        root = self._config.session_dir or _pick_default_root()
        session_dir = Path(root) / "sessions" / self.session_id
        if session_dir.is_dir():
            for ev in load_v1_base_events(session_dir):
                seen.setdefault(ev.event_id, ev)
        return sorted(seen.values(), key=lambda e: e.timestamp_ns)

    def _append_capture(self, ev: BaseEvent) -> None:
        self._capture.append(ev)
        try:
            self._capture_bytes += len(ev.model_dump_json())
        except Exception:
            pass
        max_events = self._config.max_capture_buffer_events
        max_bytes = self._config.max_capture_buffer_bytes
        while len(self._capture) > max_events or self._capture_bytes > max_bytes:
            if len(self._capture) <= 1:
                break
            old = self._capture.popleft()
            try:
                self._capture_bytes -= len(old.model_dump_json())
            except Exception:
                self._capture_bytes = max(0, self._capture_bytes - 1)

    def _append_detector_ring(self, ev: BaseEvent) -> None:
        self._detector_ring.append(ev)
        max_ring = self._config.max_detector_ring_events
        while len(self._detector_ring) > max_ring:
            self._detector_ring.popleft()

    def _must_keep(self) -> bool:
        return self.sample is SampleMode.ALL or self.head_keep

    def _activate_writer(self) -> Writer:
        if self.writer is not None:
            return self.writer
        w = get_writer(self._config)
        try:
            w.declare_session(
                self.session_id,
                sample=self.sample,
                agent_name=self.agent_name,
                start_ns=self._wall_ns,
                head_keep=self.head_keep,
                wall_ns=self._wall_ns,
                monotonic_ns=self.start_perf_ns,
            )
        except Exception:
            logger.exception("autopsy: declare_session failed")
        self.writer = w
        return w

    @classmethod
    def begin(
        cls,
        *,
        config: LensConfig,
        agent_name: str,
        sample,
        writer: Writer | None = None,
        detectors: list[str] | None = None,
        detector_overrides: Any | None = None,
    ) -> "Session":
        mode, head_keep = _resolve_sample(sample, config.default_sample)
        sid = new_ulid()
        now_perf = time.perf_counter_ns()
        wall = time.time_ns()
        defer_writer = mode is SampleMode.ERRORS and not head_keep
        w: Writer | None = None
        if not defer_writer:
            w = writer if writer is not None else get_writer(config)
            try:
                w.declare_session(
                    sid,
                    sample=mode,
                    agent_name=agent_name,
                    start_ns=wall,
                    head_keep=head_keep,
                    wall_ns=wall,
                    monotonic_ns=now_perf,
                )
            except Exception:
                logger.exception("autopsy: declare_session failed")
        sess = cls(
            session_id=sid, agent_name=agent_name, sample=mode,
            head_keep=head_keep, writer=w, config=config,
            start_perf_ns=now_perf, wall_ns=wall,
        )
        sess._detectors = detectors
        sess._detector_overrides = detector_overrides
        return sess

    def record_event(self, ev: BaseEvent) -> None:
        try:
            if ev.session_id != self.session_id:
                try:
                    ev = ev.model_copy(update={"session_id": self.session_id})
                except Exception:
                    return
            self._append_capture(ev)
            if ev.kind in _DETECTOR_RING_KINDS:
                self._append_detector_ring(ev)
            w = self.writer
            if w is None:
                if ev.kind is EventKind.ERROR:
                    w = self._activate_writer()
                    w.enqueue(ev)
                return
            w.enqueue(ev)
        except Exception:
            logger.exception("autopsy: record_event failed")

    def end(self, *, outcome: str, error_type: str | None = None) -> None:
        try:
            from autopsy.detectors.overrides import lens_config_for_detectors
            from autopsy.detectors.registry import resolve_enabled
            from autopsy.detectors.runner import run_detectors

            det_cfg = lens_config_for_detectors(
                self._config, overrides=self._detector_overrides,
            )
            verdicts = []
            if self._detectors is not None:
                enabled = self._detectors
            else:
                enabled = det_cfg.enabled_detectors
            if enabled:
                saved: list[str] | None = None
                if self._detectors is not None:
                    saved = det_cfg.enabled_detectors
                    det_cfg.enabled_detectors = list(self._detectors)
                try:
                    verdicts = run_detectors(
                        events=self.events_for_detectors(),
                        outcome=outcome,
                        session_id=self.session_id,
                        trace_id=self.session_id,
                        parent_id=None,
                        detectors=resolve_enabled(det_cfg),
                    )
                finally:
                    if saved is not None:
                        det_cfg.enabled_detectors = saved
            fails = [v for v in verdicts if v.verdict == "fail"]
            warns = [v for v in verdicts if v.verdict == "warn"]
            promote = bool(fails) or (
                bool(warns) and det_cfg.promote_on_warn
            )
            if fails:
                outcome = "error"
                error_type = error_type or f"detector:{fails[0].detector_name}"
            elif warns and det_cfg.promote_on_warn:
                error_type = error_type or f"detector_warn:{warns[0].detector_name}"

            should_finalize = promote or self.writer is not None or self._must_keep()
            if should_finalize:
                w = self.writer
                if promote:
                    if w is None:
                        w = self._activate_writer()
                    if warns and det_cfg.promote_on_warn and not fails:
                        w.mark_session_kept(self.session_id)
                    for ev in self._capture:
                        w.enqueue(ev)
                    for v in verdicts:
                        w.enqueue(v)
                w = self.writer
                if w is not None:
                    w.end_session(
                        self.session_id, outcome=outcome, error_type=error_type,
                    )
            self._capture.clear()
            self._capture_bytes = 0
            self._detector_ring.clear()
        except Exception:
            logger.exception("autopsy: end failed")
