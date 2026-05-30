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
from typing import Optional

from .config import LensConfig
from .events import BaseEvent, EventKind
from .store.local_fs import LocalFilesystemStore
from .ulid import new_ulid
from .writer import SampleMode, Writer

logger = logging.getLogger("autopsy.session")

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
        return cls(
            session_id=sid, agent_name=agent_name, sample=mode,
            head_keep=head_keep, writer=w, config=config,
            start_perf_ns=now_perf, wall_ns=wall,
        )

    def record_event(self, ev: BaseEvent) -> None:
        try:
            if ev.session_id != self.session_id:
                try:
                    ev = ev.model_copy(update={"session_id": self.session_id})
                except Exception:
                    return
            w = self.writer
            if w is None:
                if self.sample is SampleMode.ERRORS and ev.kind is not EventKind.ERROR:
                    return
                w = self._activate_writer()
            w.enqueue(ev)
        except Exception:
            logger.exception("autopsy: record_event failed")

    def end(self, *, outcome: str, error_type: str | None = None) -> None:
        if self.writer is None:
            return
        try:
            self.writer.end_session(self.session_id, outcome=outcome, error_type=error_type)
        except Exception:
            logger.exception("autopsy: end_session failed")
