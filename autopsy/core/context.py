"""ContextVars used across the capture layer.

These propagate through `await` and `asyncio.Task`. The decorator and
interceptor read them on the hot path; they are never mutated outside
the decorator/interceptor/session lifecycle.

Why ContextVars and not a thread-local: asyncio Tasks copy the ContextVar
state at task creation, so nested traces correctly observe their parent
even across `asyncio.gather`.
"""
from __future__ import annotations

import contextvars
from typing import Any

_current_session: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "autopsy_current_session", default=None
)
_current_parent_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "autopsy_current_parent_id", default=None
)
_in_diagnostics_call: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "autopsy_in_diagnostics_call", default=False
)


def current_session() -> Any:
    return _current_session.get()


def set_session(value: Any, *, token: contextvars.Token | None = None) -> contextvars.Token:
    if token is not None:
        _current_session.reset(token)
        return token
    return _current_session.set(value)


def current_parent_id() -> str | None:
    return _current_parent_id.get()


def set_parent_id(
    value: str | None, *, token: contextvars.Token | None = None
) -> contextvars.Token:
    if token is not None:
        _current_parent_id.reset(token)
        return token
    return _current_parent_id.set(value)


def is_diagnostics_call() -> bool:
    return _in_diagnostics_call.get()


def set_diagnostics_call(
    value: bool, *, token: contextvars.Token | None = None
) -> contextvars.Token:
    if token is not None:
        _in_diagnostics_call.reset(token)
        return token
    return _in_diagnostics_call.set(value)
