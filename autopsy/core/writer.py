"""Writer — single daemon thread, bounded queue, batched drain.

The writer is the only piece between the hot path and disk. It accepts
events via a non-blocking put_nowait on a bounded queue, drains them on a
daemon thread, applies the redactor, and (this task) decides per-session
whether to spill to disk or discard based on the sample state machine.

Sample state machine:
  declared -> kept  (transition: explicit "all"/head-rate keep, or any
                     ERROR event observed, or in-flight buffer cap exceeded)
  declared -> discarded  (transition: end_session called and not kept)
  kept     -> finalized  (transition: end_session)

Kept sessions are spilled to the TraceStore lazily on the FIRST event that
arrives after the transition. Sessions that never transition to kept
never touch disk at all.
"""
from __future__ import annotations

import atexit
import enum
import logging
import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import LensConfig
from .events import BaseEvent, EventKind, Manifest

logger = logging.getLogger("autopsy.writer")

_SENTINEL = object()


class SampleMode(str, enum.Enum):
    ALL = "all"
    ERRORS = "errors"
    OFF = "off"
    RATE = "rate"


@dataclass
class _SessionState:
    session_id: str
    agent_name: str
    sample: SampleMode
    start_ns: int
    wall_ns: int
    monotonic_ns: int
    head_keep: bool = False
    kept: bool = False
    ended: bool = False
    outcome: str = "ok"
    error_type: str | None = None
    partial: bool = False
    buffer: list[BaseEvent] = field(default_factory=list)
    buffer_bytes: int = 0
    event_count: int = 0
    dropped_events: int = 0
    bundle_meta: dict[str, Any] = field(default_factory=dict)


class Writer:
    _atexit_registered = False

    def __init__(self, config: LensConfig, store: Any | None = None):
        self.config = config
        self.store = store
        self._queue: queue.Queue = queue.Queue(maxsize=config.queue_maxsize)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self.dropped_events_total: int = 0
        self._sessions: dict[str, _SessionState] = {}
        self._lock = threading.Lock()
        self._per_session_buffer_for_test: dict[str, list[BaseEvent]] = defaultdict(list)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="autopsy-writer", daemon=True
        )
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def declare_session(
        self,
        session_id: str,
        *,
        sample: SampleMode,
        agent_name: str,
        start_ns: int,
        head_keep: bool = False,
        wall_ns: int | None = None,
        monotonic_ns: int | None = None,
    ) -> None:
        self._ensure_atexit_registered()
        with self._lock:
            self._sessions[session_id] = _SessionState(
                session_id=session_id,
                agent_name=agent_name,
                sample=sample,
                start_ns=start_ns,
                wall_ns=wall_ns or start_ns,
                monotonic_ns=monotonic_ns or start_ns,
                head_keep=head_keep,
                kept=(sample is SampleMode.ALL) or head_keep,
            )

    def enqueue(self, event: BaseEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events_total += 1
            with self._lock:
                state = self._sessions.get(event.session_id)
                if state is not None:
                    state.dropped_events += 1
        except Exception:
            self.dropped_events_total += 1

    def end_session(
        self,
        session_id: str,
        *,
        outcome: str,
        error_type: str | None = None,
        bundle_meta: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._queue.put_nowait(
                ("END", session_id, outcome, error_type, bundle_meta or {}),
            )
        except Exception:
            pass

    def shutdown(self, timeout: float = 2.0) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(_SENTINEL)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def atexit_flush(self, timeout: float = 2.0) -> None:
        """Drain remaining events with a bounded timeout.

        For each session that has not been explicitly ended, finalize it
        with outcome="partial" so the manifest reflects the abnormal exit.
        Safe to call more than once.
        """
        if self._stop.is_set() and not self.is_alive():
            return
        deadline = time.monotonic() + timeout
        with self._lock:
            stale = list(self._sessions.keys())
        for sid in stale:
            try:
                self._queue.put_nowait(("END", sid, "partial", None, {}))
            except Exception:
                pass
        while time.monotonic() < deadline:
            if self._queue.empty():
                break
            time.sleep(0.01)
        self.shutdown(timeout=max(0.1, deadline - time.monotonic()))

    def _ensure_atexit_registered(self) -> None:
        if Writer._atexit_registered:
            return
        atexit.register(self.atexit_flush, timeout=2.0)
        Writer._atexit_registered = True

    def pause_drain(self) -> None:
        self._paused.set()

    def resume_drain(self) -> None:
        self._paused.clear()

    def drained_count_for_test(self, session_id: str) -> int:
        with self._lock:
            return len(self._per_session_buffer_for_test.get(session_id, []))

    def drained_events_for_test(self, session_id: str) -> list[BaseEvent]:
        with self._lock:
            return list(self._per_session_buffer_for_test.get(session_id, []))

    def mark_session_kept(self, session_id: str) -> None:
        """Force a session to be retained (e.g. warn-tier detector with per-call promote_on_warn)."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state is not None:
                state.kept = True

    def snapshot_events_for_detectors(self, session_id: str) -> list[BaseEvent]:
        """In-flight writer buffer for a session (not yet spilled or after partial spill)."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return []
            return list(state.buffer)

    def flush_session_now(self, session_id: str, *, limit: int = 50_000) -> int:
        """Process queued events for one session only (safe before detector evaluation)."""
        processed = 0
        requeue: list = []
        pending: list = []
        while processed + len(pending) < limit:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _SENTINEL:
                requeue.append(item)
                continue
            if isinstance(item, tuple) and item and item[0] == "END":
                requeue.append(item)
                continue
            sid = getattr(item, "session_id", None)
            if sid == session_id:
                pending.append(item)
            else:
                requeue.append(item)
        for item in requeue:
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                self.dropped_events_total += 1
        if pending:
            self._process_batch(pending)
            processed = len(pending)
        return processed

    def flush_now(self, *, limit: int = 50_000) -> int:
        """Drain the entire writer queue synchronously (tests / shutdown helpers)."""
        processed = 0
        while processed < limit:
            batch: list = []
            while len(batch) < self.config.flush_batch_size:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is _SENTINEL:
                    try:
                        self._queue.put_nowait(_SENTINEL)
                    except queue.Full:
                        pass
                    break
                batch.append(item)
            if not batch:
                break
            self._process_batch(batch)
            processed += len(batch)
        return processed

    def accumulated_events_for_session(self, session_id: str) -> list[BaseEvent]:
        """All events processed by the writer for this session (incl. spilled batches)."""
        with self._lock:
            seen: dict[str, BaseEvent] = {}
            for ev in self._per_session_buffer_for_test.get(session_id, []):
                seen[ev.event_id] = ev
            state = self._sessions.get(session_id)
            if state is not None:
                for ev in state.buffer:
                    seen[ev.event_id] = ev
            return sorted(seen.values(), key=lambda e: e.timestamp_ns)

    def _run(self) -> None:
        interval_s = self.config.flush_interval_ms / 1000.0
        batch_size = self.config.flush_batch_size
        while not self._stop.is_set() or not self._queue.empty():
            if self._paused.is_set():
                time.sleep(0.01)
                continue
            batch: list = []
            try:
                item = self._queue.get(timeout=interval_s)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                self._drain_queue_after_sentinel()
                break
            batch.append(item)
            while len(batch) < batch_size:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is _SENTINEL:
                    break
                batch.append(nxt)
            try:
                self._process_batch(batch)
            except Exception:
                logger.exception("autopsy: writer batch processing failed")

    def _drain_queue_after_sentinel(self) -> None:
        while True:
            try:
                leftover = self._queue.get_nowait()
            except queue.Empty:
                break
            if leftover is _SENTINEL:
                continue
            try:
                self._process_batch([leftover])
            except Exception:
                logger.exception("autopsy: writer batch processing failed")

    def _process_batch(self, batch: list) -> None:
        red = self.config.redactor
        cap_bytes = self.config.max_in_flight_buffer_mb * 1024 * 1024
        with self._lock:
            for raw in batch:
                if isinstance(raw, tuple) and raw and raw[0] == "END":
                    _, sid, outcome, error_type, *rest = raw
                    meta = rest[0] if rest and isinstance(rest[0], dict) else {}
                    self._finalize_session_locked(sid, outcome, error_type, meta)
                    continue
                ev: BaseEvent | None = raw
                if red is not None:
                    try:
                        ev = red(raw)
                    except Exception:
                        logger.warning("autopsy: redactor raised; dropping event")
                        ev = None
                if ev is None:
                    continue
                state = self._sessions.get(ev.session_id)
                self._per_session_buffer_for_test[ev.session_id].append(ev)
                if state is None:
                    continue
                if state.sample is SampleMode.OFF:
                    continue
                state.buffer.append(ev)
                state.event_count += 1
                try:
                    state.buffer_bytes += len(ev.model_dump_json())
                except Exception:
                    pass
                if ev.kind is EventKind.ERROR:
                    state.kept = True
                if ev.kind is EventKind.DETECTOR_VERDICT:
                    if ev.verdict == "fail":
                        state.kept = True
                    elif ev.verdict == "warn" and self.config.promote_on_warn:
                        state.kept = True
                if state.buffer_bytes > cap_bytes and not state.kept:
                    state.kept = True
                    state.partial = True
                if state.kept and self.store is not None and state.buffer:
                    try:
                        self.store.write_events(state.session_id, state.buffer)
                    except Exception:
                        logger.exception("autopsy: store.write_events failed")
                    state.buffer = []

    def _finalize_session_locked(
        self,
        session_id: str,
        outcome: str,
        error_type: str | None,
        bundle_meta: dict[str, Any] | None = None,
    ) -> None:
        state = self._sessions.pop(session_id, None)
        if state is None:
            return
        if outcome == "error":
            state.kept = True
        if not state.kept:
            return
        if self.store is None:
            return
        try:
            if state.buffer:
                self.store.write_events(session_id, state.buffer)
                state.buffer = []
        except Exception:
            logger.exception("autopsy: final spill failed")
            state.partial = True
        end_ns = int(time.time() * 1e9)
        status: str
        if state.partial:
            status = "partial"
        elif outcome == "error":
            status = "error"
        else:
            status = "ok"
        try:
            extra = {**(state.bundle_meta or {}), **(bundle_meta or {})}
            manifest = Manifest(
                session_id=session_id,
                agent_name=state.agent_name,
                start_time_ns=state.start_ns,
                end_time_ns=end_ns,
                duration_ms=(end_ns - state.start_ns) / 1e6,
                status=status,
                error_type=error_type,
                event_count=state.event_count,
                dropped_events=state.dropped_events,
                autopsy_format_version=1,
                autopsy_version="0.2.0",
                wall_clock_ns_at_start=state.wall_ns,
                monotonic_ns_at_start=state.monotonic_ns,
                extra=extra,
            )
            self.store.finalize_session(manifest)
        except Exception:
            logger.exception("autopsy: finalize_session failed")
