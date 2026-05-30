"""Crockford-base32 ULID generator.

ULIDs are 26-character, time-sortable, 128-bit identifiers. We use them as
event IDs so events.jsonl is naturally ordered without a separate sequence
number, and so two events minted on different threads in the same millisecond
still sort deterministically.

This is a from-scratch implementation to avoid pulling in another dep.
"""
from __future__ import annotations

import os
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_lock = threading.Lock()
_last_ms: int = -1
_last_rand: int = 0


def _encode(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid() -> str:
    """Return a fresh 26-char ULID. Monotonic within a process."""
    global _last_ms, _last_rand
    with _lock:
        now_ms = int(time.time() * 1000)
        if now_ms <= _last_ms:
            _last_rand += 1
            rand = _last_rand
            ms = _last_ms
        else:
            rand = int.from_bytes(os.urandom(10), "big")
            ms = now_ms
            _last_ms = ms
            _last_rand = rand
    return _encode(ms, 10) + _encode(rand, 16)
