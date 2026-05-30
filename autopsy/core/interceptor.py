"""LLM call interceptor - monkey-patches OpenAI SDK to record LLM events."""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Tuple

from .context import current_session, is_diagnostics_call, set_diagnostics_call
from .events import (
    EventKind,
    LLMRequestEvent,
    LLMResponseEvent,
)
from .ulid import new_ulid

logger = logging.getLogger("autopsy.interceptor")


def suppress_tracing() -> contextvars.Token:
    """Set the flag to suppress tracing - returns token to reset."""
    return set_diagnostics_call(True)


def restore_tracing(token: contextvars.Token) -> None:
    try:
        set_diagnostics_call(False, token=token)
    except Exception:
        pass


def _import_openai_targets() -> Tuple[Any, Any] | None:
    """Return (async_completions_target, sync_completions_target), or None."""
    try:
        from openai.resources.chat import completions as _c
        return _c.AsyncCompletions, _c.Completions
    except Exception:
        return None


def _safe_dump(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
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


def _emit_request(session, *, model, messages, tools, temperature, max_tokens) -> str:
    nid = new_ulid()
    try:
        ev = LLMRequestEvent(
            event_id=nid,
            parent_id=None,
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKind.LLM_REQUEST,
            model=str(model or ""),
            messages=_safe_dump(messages) or [],
            tools=_safe_dump(tools) or [],
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
        ev = LLMResponseEvent(
            event_id=new_ulid(),
            parent_id=None,
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKind.LLM_RESPONSE,
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


class InterceptorManager:
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
