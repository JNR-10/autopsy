"""Default redactor and secret-pattern scrubber.

Scope:
- Common API-key shapes (OpenAI sk-, Bearer tokens, AWS access keys, OAuth-shaped
  long tokens). Best-effort, not exhaustive.
- Does NOT do PII detection — that's a downstream concern. Users supply a
  custom redactor on LensConfig.redactor if they need PII handling.

The redactor returns:
- A new event with scrubbed values (preferred).
- None to drop the event entirely.
- Raises only if the user-supplied redactor itself raises — callers catch
  RedactorError and fail-closed (drop the event).
"""
from __future__ import annotations

import re
from typing import Any

from .events_v2 import BaseEvent

REDACTED = "[REDACTED:secret]"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]{10,}", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"ya29\.[0-9A-Za-z_\-]+"),
    re.compile(r"xox[abprs]-[0-9A-Za-z\-]{10,}"),
]


def scrub_secrets(s: str) -> str:
    out = s
    for pat in _PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def _walk(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_secrets(value)
    if isinstance(value, dict):
        return {k: _walk(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_walk(v) for v in value)
    return value


def default_redactor(event: BaseEvent) -> BaseEvent | None:
    """Walk every field on the event, scrubbing matching secret patterns.

    Returns the (possibly-modified) event. Returns None only if a future
    policy decides to drop the event; today this function never drops.
    """
    data = event.model_dump()
    scrubbed = _walk(data)
    if scrubbed == data:
        return event
    return type(event).model_validate(scrubbed)
