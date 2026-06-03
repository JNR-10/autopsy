"""@lens.trace decorator - the public surface for instrumenting an agent."""
from __future__ import annotations

import asyncio
import functools
import logging
import time

from .config import LensConfig as _LensConfig
from autopsy.detectors.overrides import DetectorCallOverrides
from .context import current_parent_id, current_session, set_parent_id, set_session
from .replay import consume_frozen_output
from .events import AgentEndEvent, AgentStartEvent, ErrorEvent, EventKind
from .session import Session as _Session
from .ulid import new_ulid
from .writer import SampleMode

logger = logging.getLogger("autopsy.decorator")


def _preview(value, limit: int = 512) -> str:
    try:
        s = repr(value)
    except Exception:
        s = "<unrepr>"
    return s[:limit]


class LensDecorator:
    """The new @lens.trace.

    - Sync wrapper calls fn() directly. No asyncio.run, no event loop spinup.
    - Async wrapper is an `async def`. The trace emission is synchronous
      (Writer.enqueue is put_nowait), so the await chain is untouched.
    - Nested calls share the root session via the `current_session` ContextVar.
    """

    def __init__(self, config: _LensConfig | None = None):
        self.config = config or _LensConfig()

    def set_ws_manager(self, ws_manager) -> None:
        """No-op stub kept for server wiring compatibility."""

    def trace(
        self,
        fn=None,
        *,
        sample=None,
        name=None,
        detectors=None,
        detector_profile=None,
        promote_on_warn=None,
        tool_loop_threshold=None,
        max_tool_calls=None,
        latency_threshold_ms=None,
        duplicate_tool_threshold=None,
        error_storm_threshold=None,
    ):
        _ov_args = (
            detector_profile, promote_on_warn, tool_loop_threshold, max_tool_calls,
            latency_threshold_ms, duplicate_tool_threshold, error_storm_threshold,
        )
        overrides = (
            DetectorCallOverrides(
                detector_profile=detector_profile,
                promote_on_warn=promote_on_warn,
                tool_loop_threshold=tool_loop_threshold,
                max_tool_calls=max_tool_calls,
                latency_threshold_ms=latency_threshold_ms,
                duplicate_tool_threshold=duplicate_tool_threshold,
                error_storm_threshold=error_storm_threshold,
            )
            if any(x is not None for x in _ov_args)
            else None
        )
        if fn is None:
            return lambda f: self.trace(
                f,
                sample=sample,
                name=name,
                detectors=detectors,
                detector_profile=detector_profile,
                promote_on_warn=promote_on_warn,
                tool_loop_threshold=tool_loop_threshold,
                max_tool_calls=max_tool_calls,
                latency_threshold_ms=latency_threshold_ms,
                duplicate_tool_threshold=duplicate_tool_threshold,
                error_storm_threshold=error_storm_threshold,
            )
        return self._wrap(
            fn, sample=sample, name=name, detectors=detectors, overrides=overrides,
        )

    def _wrap(self, fn, *, sample, name, detectors, overrides=None):
        is_coro = asyncio.iscoroutinefunction(fn)
        agent_name = name or getattr(fn, "__name__", "agent")

        if is_coro:
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                return await self._invoke_async(
                    fn, args, kwargs,
                    sample=sample, agent_name=agent_name, detectors=detectors,
                    overrides=overrides,
                )
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            return self._invoke_sync(
                fn, args, kwargs,
                sample=sample, agent_name=agent_name, detectors=detectors,
                overrides=overrides,
            )
        return sync_wrapper

    def _begin_or_join(self, sample, agent_name, detectors=None, overrides=None, fn=None):
        existing = current_session()
        if existing is not None:
            return existing, False
        session = _Session.begin(
            config=self.config, agent_name=agent_name, sample=sample,
            detectors=detectors, detector_overrides=overrides,
        )
        if fn is not None:
            session.capture_agent_metadata(fn)
        set_session(session)
        return session, True

    def _emit_agent_start(self, session, agent_name, input_preview):
        node_id = new_ulid()
        parent_id = current_parent_id()
        try:
            ev = AgentStartEvent(
                event_id=node_id,
                parent_id=parent_id,
                session_id=session.session_id,
                trace_id=session.session_id,
                timestamp_ns=time.time_ns(),
                kind=EventKind.AGENT_START,
                agent_name=agent_name,
                role="agent",
                input_preview=input_preview,
            )
            session.record_event(ev)
        except Exception:
            pass
        return node_id

    def _emit_agent_end(self, session, node_id, parent_id, duration_ms, output_preview):
        try:
            ev = AgentEndEvent(
                event_id=new_ulid(),
                parent_id=parent_id,
                session_id=session.session_id,
                trace_id=session.session_id,
                timestamp_ns=time.time_ns(),
                kind=EventKind.AGENT_END,
                duration_ms=duration_ms,
                output_preview=output_preview,
            )
            session.record_event(ev)
        except Exception:
            pass
        if node_id:
            session.replay_checkpoints[node_id] = output_preview

    def _emit_error(self, session, node_id, parent_id, exc):
        import traceback as tb
        try:
            ev = ErrorEvent(
                event_id=new_ulid(),
                parent_id=node_id,
                session_id=session.session_id,
                trace_id=session.session_id,
                timestamp_ns=time.time_ns(),
                kind=EventKind.ERROR,
                error_type=type(exc).__name__,
                error_message=str(exc)[:2000],
                traceback=tb.format_exc()[:8000],
            )
            session.record_event(ev)
        except Exception:
            pass

    async def _invoke_async(
        self, fn, args, kwargs, *, sample, agent_name, detectors=None, overrides=None,
    ):
        session, is_root = self._begin_or_join(
            sample, agent_name, detectors=detectors, overrides=overrides, fn=fn,
        )
        if is_root and args:
            session.input_query = _preview(args[0])
        track = session.sample is not SampleMode.ERRORS
        node_id = None
        parent_token = None
        if track:
            node_id = self._emit_agent_start(
                session, agent_name, _preview(args[0] if args else kwargs),
            )
            parent_token = set_parent_id(node_id)
        start = time.perf_counter()
        try:
            frozen = consume_frozen_output()
            if frozen is not None:
                result = frozen
            else:
                result = await fn(*args, **kwargs)
            if track:
                self._emit_agent_end(
                    session, node_id, current_parent_id(),
                    (time.perf_counter() - start) * 1000.0, _preview(result),
                )
            if is_root:
                session.end(outcome="ok")
            return result
        except Exception as exc:
            if not track:
                session._activate_writer()
                node_id = self._emit_agent_start(
                    session, agent_name, _preview(args[0] if args else kwargs),
                )
                parent_token = set_parent_id(node_id)
            self._emit_error(session, node_id, current_parent_id(), exc)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (time.perf_counter() - start) * 1000.0, "",
            )
            if is_root:
                session.end(outcome="error", error_type=type(exc).__name__)
            raise
        finally:
            if parent_token is not None:
                set_parent_id(None, token=parent_token)
            if is_root:
                set_session(None)

    def _invoke_sync(
        self, fn, args, kwargs, *, sample, agent_name, detectors=None, overrides=None,
    ):
        session, is_root = self._begin_or_join(
            sample, agent_name, detectors=detectors, overrides=overrides, fn=fn,
        )
        if is_root and args:
            session.input_query = _preview(args[0])
        track = session.sample is not SampleMode.ERRORS
        node_id = None
        parent_token = None
        if track:
            node_id = self._emit_agent_start(
                session, agent_name, _preview(args[0] if args else kwargs),
            )
            parent_token = set_parent_id(node_id)
        start = time.perf_counter()
        try:
            frozen = consume_frozen_output()
            if frozen is not None:
                result = frozen
            else:
                result = fn(*args, **kwargs)
            if track:
                self._emit_agent_end(
                    session, node_id, current_parent_id(),
                    (time.perf_counter() - start) * 1000.0, _preview(result),
                )
            if is_root:
                session.end(outcome="ok")
            return result
        except Exception as exc:
            if not track:
                session._activate_writer()
                node_id = self._emit_agent_start(
                    session, agent_name, _preview(args[0] if args else kwargs),
                )
                parent_token = set_parent_id(node_id)
            self._emit_error(session, node_id, current_parent_id(), exc)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (time.perf_counter() - start) * 1000.0, "",
            )
            if is_root:
                session.end(outcome="error", error_type=type(exc).__name__)
            raise
        finally:
            if parent_token is not None:
                set_parent_id(None, token=parent_token)
            if is_root:
                set_session(None)
