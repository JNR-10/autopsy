"""LLM call interceptor - monkey-patches OpenAI SDK to record LLM events.

Strategy:
- We patch openai.resources.chat.completions.AsyncCompletions.create.
- The patched create() emits LLMRequestEvent before the call and LLMResponseEvent
  after.
- The patch uses contextvars to determine the active TraceSession - if none, it
  passes through unchanged. This means it is safe to import the patched module
  even when autopsy is not actively tracing.
- For non-OpenAI providers (LangChain, raw httpx), the same OpenAI patch covers
  them when they use the OpenAI Python SDK with a custom base_url (the most
  common case for GMI, Together, etc.).
- A context variable _in_diagnostics_call suppresses tracing for nested
  diagnostics LLM calls so they don't pollute the user's session.

The interceptor is intentionally defensive - if any part fails, the original
function is still invoked so the user's agent always works.
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
from typing import Any, Tuple

from .context import current_session, is_diagnostics_call
from .events import LLMRequestEvent, LLMResponseEvent, ToolCallEvent
from .events_v2 import (
    EventKind as EventKindV2,
    LLMRequestEvent as LLMRequestEventV2,
    LLMResponseEvent as LLMResponseEventV2,
)
from .tracer import get_current_session
from .ulid import new_ulid

logger = logging.getLogger("autopsy.interceptor")

_in_diagnostics_call: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_in_diagnostics_call", default=False
)


def suppress_tracing() -> contextvars.Token:
    """Set the flag to suppress tracing - returns token to reset."""
    return _in_diagnostics_call.set(True)


def restore_tracing(token: contextvars.Token) -> None:
    try:
        _in_diagnostics_call.reset(token)
    except Exception:
        pass


def _estimate_tokens(messages: list[dict], model: str) -> int:
    """Approximate prompt tokens. Falls back to char/4 for non-OpenAI models."""
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        total = 0
        for m in messages or []:
            c = m.get("content")
            if isinstance(c, str):
                total += len(enc.encode(c))
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        total += len(enc.encode(part["text"]))
        return total
    except Exception:
        try:
            total_chars = 0
            for m in messages or []:
                c = m.get("content")
                if isinstance(c, str):
                    total_chars += len(c)
                elif isinstance(c, list):
                    for part in c:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            total_chars += len(part["text"])
            return total_chars // 4
        except Exception:
            return 0


def _safe_dump(obj: Any) -> Any:
    """Convert SDK objects (pydantic models) to JSON-safe dicts."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_dump(v) for v in obj]
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _safe_dump(fn())
            except Exception:
                continue
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


class _PatchedCreate:
    """Wraps the original AsyncCompletions.create method."""

    def __init__(self, original):
        self._original = original

    async def __call__(self, *args, **kwargs):
        # Pass-through if tracing is suppressed or there's no active session.
        if _in_diagnostics_call.get():
            return await self._original(*args, **kwargs)
        session = get_current_session()
        if session is None:
            return await self._original(*args, **kwargs)

        from .decorator import current_node_id

        node_id = current_node_id() or "root"
        model = kwargs.get("model", "")
        messages = kwargs.get("messages", []) or []
        tools = kwargs.get("tools", []) or []
        temperature = kwargs.get("temperature", 1.0)
        max_tokens = kwargs.get("max_tokens", 0) or 0
        stream = kwargs.get("stream", False)

        prompt_estimate = _estimate_tokens(messages, model)

        req_ev = LLMRequestEvent(
            session_id=session.session_id,
            node_id=node_id,
            model=str(model),
            messages=_safe_dump(messages) or [],
            temperature=float(temperature) if temperature is not None else 1.0,
            max_tokens=int(max_tokens) if max_tokens else 0,
            tools=_safe_dump(tools) or [],
            prompt_tokens_estimate=int(prompt_estimate),
        )
        try:
            await session.emit(req_ev)
        except Exception:
            logger.exception("autopsy: emit llm_request failed")

        t0 = time.perf_counter()
        try:
            result = await self._original(*args, **kwargs)
        except Exception as exc:
            # Emit a failed response so the dashboard shows what happened.
            try:
                resp_ev = LLMResponseEvent(
                    session_id=session.session_id,
                    node_id=node_id,
                    model=str(model),
                    content="",
                    tool_calls=[],
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    finish_reason=f"error:{type(exc).__name__}",
                )
                await session.emit(resp_ev)
            except Exception:
                pass
            raise

        # Streaming path: collect chunks then emit one synthetic response.
        if stream:
            return self._wrap_stream(result, session, node_id, model, t0)

        # Non-streaming path.
        try:
            content = ""
            tool_calls_list: list[dict] = []
            usage = None
            finish_reason = ""
            choices = getattr(result, "choices", None) or []
            if choices:
                msg = getattr(choices[0], "message", None)
                content = getattr(msg, "content", "") or ""
                raw_tools = getattr(msg, "tool_calls", None) or []
                for tc in raw_tools:
                    tool_calls_list.append({
                        "id": getattr(tc, "id", ""),
                        "type": getattr(tc, "type", "function"),
                        "name": getattr(getattr(tc, "function", None), "name", ""),
                        "arguments": getattr(
                            getattr(tc, "function", None), "arguments", ""),
                    })
                finish_reason = getattr(choices[0], "finish_reason", "") or ""
            usage_obj = getattr(result, "usage", None)
            if usage_obj is not None:
                usage = {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
                }
            resp_ev = LLMResponseEvent(
                session_id=session.session_id,
                node_id=node_id,
                model=str(model),
                content=content or "",
                tool_calls=tool_calls_list,
                prompt_tokens=(usage or {}).get("prompt_tokens", 0),
                completion_tokens=(usage or {}).get("completion_tokens", 0),
                total_tokens=(usage or {}).get("total_tokens", 0),
                latency_ms=(time.perf_counter() - t0) * 1000,
                finish_reason=finish_reason,
            )
            await session.emit(resp_ev)

            # Also emit tool_call events for any tools the model invoked.
            for tc in tool_calls_list:
                try:
                    args_parsed: dict = {}
                    raw_args = tc.get("arguments")
                    if isinstance(raw_args, str) and raw_args.strip():
                        try:
                            args_parsed = json.loads(raw_args)
                        except Exception:
                            args_parsed = {"_raw": raw_args}
                    elif isinstance(raw_args, dict):
                        args_parsed = raw_args
                    tool_ev = ToolCallEvent(
                        session_id=session.session_id,
                        node_id=node_id,
                        tool_name=tc.get("name", ""),
                        tool_args=args_parsed,
                    )
                    await session.emit(tool_ev)
                except Exception:
                    logger.exception("autopsy: emit tool_call failed")
        except Exception:
            logger.exception("autopsy: emit llm_response failed")

        return result

    def _wrap_stream(self, original_stream, session, node_id, model, t0):
        """Wrap an async stream to accumulate content and emit at the end."""
        async def gen():
            content_parts: list[str] = []
            finish_reason = ""
            try:
                async for chunk in original_stream:
                    try:
                        choices = getattr(chunk, "choices", None) or []
                        if choices:
                            delta = getattr(choices[0], "delta", None)
                            c = getattr(delta, "content", None) if delta else None
                            if c:
                                content_parts.append(c)
                            fr = getattr(choices[0], "finish_reason", None)
                            if fr:
                                finish_reason = fr
                    except Exception:
                        pass
                    yield chunk
            finally:
                try:
                    full = "".join(content_parts)
                    resp_ev = LLMResponseEvent(
                        session_id=session.session_id,
                        node_id=node_id,
                        model=str(model),
                        content=full,
                        tool_calls=[],
                        prompt_tokens=0,
                        completion_tokens=len(full) // 4,
                        total_tokens=len(full) // 4,
                        latency_ms=(time.perf_counter() - t0) * 1000,
                        finish_reason=finish_reason or "stop",
                    )
                    await session.emit(resp_ev)
                except Exception:
                    logger.exception("autopsy: stream emit failed")
        return gen()


class InterceptorManager:
    """Globally installed once; uses session refcount to know when to uninstall."""

    _original_create = None
    _active_sessions: set = set()
    _lock_held: bool = False

    @classmethod
    def install(cls, session) -> None:
        cls._active_sessions.add(id(session))
        if cls._original_create is not None:
            return
        try:
            from openai.resources.chat import completions as _c
            target = _c.AsyncCompletions
            cls._original_create = target.create

            async def patched_create(self, *args, **kwargs):
                # Bind the original to its instance and pass through to the wrapper.
                bound_original = cls._original_create.__get__(self, type(self))
                wrapper = _PatchedCreate(bound_original)
                return await wrapper(*args, **kwargs)

            target.create = patched_create
        except Exception:
            logger.exception("autopsy: failed to install OpenAI interceptor")

    @classmethod
    def uninstall(cls, session) -> None:
        cls._active_sessions.discard(id(session))
        if cls._active_sessions:
            return
        if cls._original_create is None:
            return
        try:
            from openai.resources.chat import completions as _c
            _c.AsyncCompletions.create = cls._original_create
        except Exception:
            logger.exception("autopsy: failed to uninstall OpenAI interceptor")
        finally:
            cls._original_create = None


# ----- new v2 interceptor (added in phase 5; replaces old InterceptorManager in phase 7) -----


def _import_openai_targets() -> Tuple[Any, Any] | None:
    """Return (async_completions_target, sync_completions_target), or None.

    Lazy-imports openai so a missing package is a silent no-op. Both targets
    are class instances that the patch will monkey-patch `create` on.
    """
    try:
        from openai.resources.chat import completions as _c
        return _c.AsyncCompletions, _c.Completions
    except Exception:
        return None


def _safe_dump_v2(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_dump_v2(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_dump_v2(v) for v in obj]
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _safe_dump_v2(fn())
            except Exception:
                continue
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


def _emit_request(session, *, model, messages, tools, temperature, max_tokens) -> str:
    nid = new_ulid()
    try:
        ev = LLMRequestEventV2(
            event_id=nid,
            parent_id=None,
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKindV2.LLM_REQUEST,
            model=str(model or ""),
            messages=_safe_dump_v2(messages) or [],
            tools=_safe_dump_v2(tools) or [],
            temperature=float(temperature) if temperature is not None else 1.0,
            max_tokens=int(max_tokens or 0),
            prompt_tokens_estimate=0,
        )
        session.record_event(ev)
    except Exception:
        pass
    return nid


def _emit_response(session, *, model, result, latency_ms):
    try:
        content = ""
        finish_reason = ""
        usage = None
        choices = getattr(result, "choices", None) or []
        if choices:
            msg = getattr(choices[0], "message", None)
            content = getattr(msg, "content", "") or ""
            finish_reason = getattr(choices[0], "finish_reason", "") or ""
        usage_obj = getattr(result, "usage", None)
        if usage_obj is not None:
            usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
            }
        ev = LLMResponseEventV2(
            event_id=new_ulid(),
            parent_id=None,
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKindV2.LLM_RESPONSE,
            model=str(model or ""),
            content=content,
            tool_calls=[],
            prompt_tokens=(usage or {}).get("prompt_tokens", 0),
            completion_tokens=(usage or {}).get("completion_tokens", 0),
            total_tokens=(usage or {}).get("total_tokens", 0),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
        session.record_event(ev)
    except Exception:
        pass


class InterceptorV2Manager:
    """Patch openai's chat.completions.create (both sync and async).

    Lazy-imports openai; silently no-ops if openai is not installed.
    Refcounted-by-install so multiple sessions don't double-patch.
    """

    _installed_count: int = 0
    _async_original = None
    _sync_original = None
    _async_target = None
    _sync_target = None

    def install(self) -> None:
        cls = type(self)
        cls._installed_count += 1
        if cls._async_original is not None or cls._sync_original is not None:
            return
        targets = _import_openai_targets()
        if targets is None:
            return
        async_target, sync_target = targets
        cls._async_target = async_target
        cls._sync_target = sync_target
        cls._async_original = getattr(async_target, "create", None)
        cls._sync_original = getattr(sync_target, "create", None)

        async_orig = cls._async_original
        sync_orig = cls._sync_original

        async def _await_orig(orig, self_, *args, **kwargs):
            if not callable(orig):
                return await async_target.create(*args, **kwargs)
            if getattr(orig, "__self__", None) is not None:
                return await orig(*args, **kwargs)
            return await orig(self_, *args, **kwargs)

        def _call_orig(orig, self_, *args, **kwargs):
            if not callable(orig):
                return sync_target.create(*args, **kwargs)
            if getattr(orig, "__self__", None) is not None:
                return orig(*args, **kwargs)
            return orig(self_, *args, **kwargs)

        async def patched_async_create(self_, *args, **kwargs):
            if is_diagnostics_call():
                return await _await_orig(async_orig, self_, *args, **kwargs)
            session = current_session()
            if session is None:
                return await _await_orig(async_orig, self_, *args, **kwargs)
            import time as _t
            _emit_request(
                session,
                model=kwargs.get("model"),
                messages=kwargs.get("messages") or [],
                tools=kwargs.get("tools") or [],
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens"),
            )
            t0 = _t.perf_counter()
            result = await _await_orig(async_orig, self_, *args, **kwargs)
            _emit_response(
                session, model=kwargs.get("model"),
                result=result, latency_ms=(_t.perf_counter() - t0) * 1000.0,
            )
            return result

        def patched_sync_create(self_, *args, **kwargs):
            if is_diagnostics_call():
                return _call_orig(sync_orig, self_, *args, **kwargs)
            session = current_session()
            if session is None:
                return _call_orig(sync_orig, self_, *args, **kwargs)
            import time as _t
            _emit_request(
                session,
                model=kwargs.get("model"),
                messages=kwargs.get("messages") or [],
                tools=kwargs.get("tools") or [],
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens"),
            )
            t0 = _t.perf_counter()
            result = _call_orig(sync_orig, self_, *args, **kwargs)
            _emit_response(
                session, model=kwargs.get("model"),
                result=result, latency_ms=(_t.perf_counter() - t0) * 1000.0,
            )
            return result

        try:
            if isinstance(async_target, type):
                async_target.create = patched_async_create
            else:
                import types
                async_target.create = types.MethodType(patched_async_create, async_target)
        except Exception:
            pass
        try:
            if isinstance(sync_target, type):
                sync_target.create = patched_sync_create
            else:
                import types
                sync_target.create = types.MethodType(patched_sync_create, sync_target)
        except Exception:
            pass

    def uninstall(self) -> None:
        cls = type(self)
        cls._installed_count = max(0, cls._installed_count - 1)
        if cls._installed_count > 0:
            return
        try:
            if cls._async_target is not None and cls._async_original is not None:
                cls._async_target.create = cls._async_original
        except Exception:
            pass
        try:
            if cls._sync_target is not None and cls._sync_original is not None:
                cls._sync_target.create = cls._sync_original
        except Exception:
            pass
        cls._async_original = None
        cls._sync_original = None
        cls._async_target = None
        cls._sync_target = None
