"""@lens.trace decorator - the public surface for instrumenting an agent.

Behaviour:
- Wraps an async function and captures all nested calls + LLM/tool events.
- Uses contextvars to track node depth and parent linkage across awaits.
- Creates a TraceSession on the top-level call; nested calls join it.
- On exception: emits NodeErrorEvent then re-raises (never swallows).
- Bug-resilient: any failure in the tracing layer is logged but never crashes
  the user's agent.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import hashlib
import inspect
import json
import logging
import time
from typing import Any, Callable, Optional
from uuid import uuid4

from .config import LensConfig as _LensConfig
from .context import (
    current_parent_id,
    current_session,
    set_parent_id,
    set_session,
)
from .events import NodeEndEvent, NodeErrorEvent, NodeStartEvent
from .events_v2 import (
    AgentEndEvent,
    AgentStartEvent,
    ErrorEvent,
    EventKind,
)
from .session import Session as _Session
from .tracer import TraceSession, get_current_session, set_current_session
from .ulid import new_ulid

logger = logging.getLogger("autopsy.decorator")

_current_node_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_node_id", default=None
)
_call_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_call_depth", default=0
)


def current_node_id() -> Optional[str]:
    return _current_node_id.get()


def _safe_serialize(obj: Any, limit: int = 50_000) -> Any:
    """JSON-safe representation. Never raises."""
    try:
        s = json.dumps(obj, default=str)
        if len(s) > limit:
            return {"__truncated": True, "size": len(s), "preview": s[:1000]}
        return json.loads(s)
    except Exception:
        try:
            return str(obj)[:limit]
        except Exception:
            return "<unserializable>"


def _output_hash(obj: Any) -> str:
    try:
        s = json.dumps(obj, default=str, sort_keys=True)
    except Exception:
        s = str(obj)
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:12]


class LensDecorator:
    """The object users access via `autopsy.lens`.

    Supports both forms::

        @lens.trace
        async def agent(query): ...

        @lens.trace(name="my-agent", node_type="agent")
        async def agent(query): ...
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._ws_manager = None

    def set_ws_manager(self, ws_manager) -> None:
        """Called by the server at startup to wire in live broadcast."""
        self._ws_manager = ws_manager

    def trace(
        self,
        fn: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        node_type: str = "agent",
    ):
        if fn is None:
            return lambda f: self.trace(f, name=name, node_type=node_type)
        return self._wrap(fn, name=name, node_type=node_type)

    def _wrap(self, fn: Callable, *, name: Optional[str], node_type: str):
        try:
            _agent_module_path = inspect.getfile(fn)
        except Exception:
            _agent_module_path = ""
        _agent_fn_name = f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', fn.__name__)}"
        is_coro = asyncio.iscoroutinefunction(fn)

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            return await self._invoke(
                fn, args, kwargs, name=name, node_type=node_type,
                module_path=_agent_module_path, fn_name=_agent_fn_name,
                is_coro=True,
            )

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            # Run the sync function inside an event loop so tracing works.
            try:
                asyncio.get_running_loop()
                # We're inside a loop already; the user shouldn't do this for sync fns.
                # Best effort: just call the function unwrapped.
                return fn(*args, **kwargs)
            except RuntimeError:
                pass
            return asyncio.run(self._invoke(
                fn, args, kwargs, name=name, node_type=node_type,
                module_path=_agent_module_path, fn_name=_agent_fn_name,
                is_coro=False,
            ))

        return async_wrapper if is_coro else sync_wrapper

    async def _invoke(
        self,
        fn: Callable,
        args: tuple,
        kwargs: dict,
        *,
        name: Optional[str],
        node_type: str,
        module_path: str,
        fn_name: str,
        is_coro: bool,
    ) -> Any:
        # Determine session lifecycle.
        session = get_current_session()
        is_root = session is None
        token_session = None
        if is_root:
            try:
                first_arg = args[0] if args else kwargs
                input_query = str(first_arg)[:5000]
            except Exception:
                input_query = ""
            session = TraceSession(
                agent_name=name or getattr(fn, "__name__", "agent"),
                input_query=input_query,
                agent_module_path=module_path,
                agent_fn_name=fn_name,
                ws_manager=self._ws_manager,
            )
            token_session = _current_node_id.set(None)  # ensure clean
            set_current_session(session)
            session.install_interceptors()

        depth = _call_depth.get()
        parent_id = _current_node_id.get()
        node_id = uuid4().hex[:12]

        start_perf = time.perf_counter()
        try:
            input_repr = _safe_serialize({"args": args, "kwargs": kwargs})
        except Exception:
            input_repr = None

        await session.emit(NodeStartEvent(
            session_id=session.session_id,
            node_id=node_id,
            node_type=node_type,
            node_name=name or getattr(fn, "__name__", "agent"),
            parent_node_id=parent_id,
            depth=depth,
            input_data=input_repr,
        ))

        node_token = _current_node_id.set(node_id)
        depth_token = _call_depth.set(depth + 1)
        try:
            if is_coro:
                result = await fn(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
            duration_ms = (time.perf_counter() - start_perf) * 1000
            await session.emit(NodeEndEvent(
                session_id=session.session_id,
                node_id=node_id,
                duration_ms=duration_ms,
                output_data=_safe_serialize(result),
                output_hash=_output_hash(result),
            ))
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_perf) * 1000
            import traceback as tb
            await session.emit(NodeErrorEvent(
                session_id=session.session_id,
                node_id=node_id,
                error_type=type(exc).__name__,
                error_message=str(exc)[:2000],
                traceback=tb.format_exc()[:8000],
                duration_ms=duration_ms,
            ))
            raise
        finally:
            try:
                _current_node_id.reset(node_token)
            except Exception:
                pass
            try:
                _call_depth.reset(depth_token)
            except Exception:
                pass
            if is_root:
                try:
                    await session.finalize()
                except Exception:
                    logger.exception("autopsy: finalize failed")
                try:
                    session.uninstall_interceptors()
                except Exception:
                    pass
                set_current_session(None)
                if token_session is not None:
                    try:
                        _current_node_id.reset(token_session)
                    except Exception:
                        pass


# ----- new v2 decorator (added in phase 5; replaces LensDecorator in phase 7) -----


def _preview(value, limit: int = 512) -> str:
    try:
        s = repr(value)
    except Exception:
        s = "<unrepr>"
    return s[:limit]


class LensV2Decorator:
    """The new @lens.trace. Replaces LensDecorator in phase 7.

    - Sync wrapper calls fn() directly. No asyncio.run, no event loop spinup.
    - Async wrapper is an `async def`. The trace emission is synchronous
      (Writer.enqueue is put_nowait), so the await chain is untouched.
    - Nested calls share the root session via the `current_session` ContextVar.
    """

    def __init__(self, config: _LensConfig | None = None):
        self.config = config or _LensConfig()

    def trace(self, fn=None, *, sample=None, name=None):
        if fn is None:
            return lambda f: self.trace(f, sample=sample, name=name)
        return self._wrap(fn, sample=sample, name=name)

    def _wrap(self, fn, *, sample, name):
        import asyncio
        import functools

        is_coro = asyncio.iscoroutinefunction(fn)
        agent_name = name or getattr(fn, "__name__", "agent")

        if is_coro:
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                return await self._invoke_async(
                    fn, args, kwargs, sample=sample, agent_name=agent_name,
                )
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            return self._invoke_sync(
                fn, args, kwargs, sample=sample, agent_name=agent_name,
            )
        return sync_wrapper

    def _begin_or_join(self, sample, agent_name):
        existing = current_session()
        if existing is not None:
            return existing, False
        session = _Session.begin(
            config=self.config, agent_name=agent_name, sample=sample,
        )
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
                timestamp_ns=__import__("time").time_ns(),
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
                timestamp_ns=__import__("time").time_ns(),
                kind=EventKind.AGENT_END,
                duration_ms=duration_ms,
                output_preview=output_preview,
            )
            session.record_event(ev)
        except Exception:
            pass

    def _emit_error(self, session, node_id, parent_id, exc):
        import traceback as tb
        try:
            ev = ErrorEvent(
                event_id=new_ulid(),
                parent_id=node_id,
                session_id=session.session_id,
                trace_id=session.session_id,
                timestamp_ns=__import__("time").time_ns(),
                kind=EventKind.ERROR,
                error_type=type(exc).__name__,
                error_message=str(exc)[:2000],
                traceback=tb.format_exc()[:8000],
            )
            session.record_event(ev)
        except Exception:
            pass

    async def _invoke_async(self, fn, args, kwargs, *, sample, agent_name):
        import time as _t
        session, is_root = self._begin_or_join(sample, agent_name)
        node_id = self._emit_agent_start(
            session, agent_name, _preview(args[0] if args else kwargs),
        )
        parent_token = set_parent_id(node_id)
        start = _t.perf_counter()
        try:
            result = await fn(*args, **kwargs)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, _preview(result),
            )
            return result
        except Exception as exc:
            self._emit_error(session, node_id, current_parent_id(), exc)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, "",
            )
            if is_root:
                session.end(outcome="error", error_type=type(exc).__name__)
            raise
        finally:
            set_parent_id(None, token=parent_token)
            if is_root:
                try:
                    session.end(outcome="ok")
                except Exception:
                    pass
                set_session(None)

    def _invoke_sync(self, fn, args, kwargs, *, sample, agent_name):
        import time as _t
        session, is_root = self._begin_or_join(sample, agent_name)
        node_id = self._emit_agent_start(
            session, agent_name, _preview(args[0] if args else kwargs),
        )
        parent_token = set_parent_id(node_id)
        start = _t.perf_counter()
        try:
            result = fn(*args, **kwargs)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, _preview(result),
            )
            return result
        except Exception as exc:
            self._emit_error(session, node_id, current_parent_id(), exc)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, "",
            )
            if is_root:
                session.end(outcome="error", error_type=type(exc).__name__)
            raise
        finally:
            set_parent_id(None, token=parent_token)
            if is_root:
                try:
                    session.end(outcome="ok")
                except Exception:
                    pass
                set_session(None)
