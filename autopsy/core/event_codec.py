"""Session event encoding: JSONL (default) or length-prefixed MessagePack (msgspec)."""
from __future__ import annotations

import gzip
import json
import logging
import struct
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Literal, TextIO

from .events import BaseEvent

logger = logging.getLogger("autopsy.event_codec")

EventEncoding = Literal["json", "msgspec"]
_FRAME_HEADER = struct.Struct(">I")

_JSON_PLAIN = "events.jsonl"
_JSON_GZ = "events.jsonl.gz"
_MSGPACK_PLAIN = "events.msgpack"
_MSGPACK_GZ = "events.msgpack.gz"


def normalize_event_encoding(raw: str) -> EventEncoding:
    value = (raw or "json").strip().lower()
    if value not in ("json", "msgspec"):
        logger.warning("autopsy: unknown event encoding %r, using json", raw)
        return "json"
    if value == "msgspec" and not msgspec_available():
        logger.warning(
            "autopsy: msgspec not installed (pip install agent-autopsy[fast]), using json",
        )
        return "json"
    return value  # type: ignore[return-value]


def msgspec_available() -> bool:
    try:
        import msgspec  # noqa: F401
        return True
    except ImportError:
        return False


def _require_msgspec():
    import msgspec
    return msgspec


def encode_events_chunk(events: Iterable[BaseEvent], encoding: EventEncoding) -> bytes:
    """Serialize a batch of events for append to the session events file."""
    if encoding == "json":
        parts: list[bytes] = []
        for ev in events:
            parts.append(ev.model_dump_json().encode("utf-8"))
            parts.append(b"\n")
        return b"".join(parts)
    msgspec = _require_msgspec()
    out = bytearray()
    for ev in events:
        payload = msgspec.msgpack.encode(ev.model_dump(mode="json"))
        out.extend(_FRAME_HEADER.pack(len(payload)))
        out.extend(payload)
    return bytes(out)


def _iter_jsonl_dicts(text: TextIO) -> Iterable[dict[str, Any]]:
    for line in text:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            logger.warning("autopsy: skipping malformed JSONL event line")


def _iter_msgpack_dicts(binary: BinaryIO) -> Iterable[dict[str, Any]]:
    msgspec = _require_msgspec()
    while True:
        header = binary.read(_FRAME_HEADER.size)
        if not header:
            break
        if len(header) < _FRAME_HEADER.size:
            logger.warning("autopsy: truncated msgpack frame header")
            break
        (length,) = _FRAME_HEADER.unpack(header)
        if length <= 0 or length > 64 * 1024 * 1024:
            logger.warning("autopsy: invalid msgpack frame length %s", length)
            break
        payload = binary.read(length)
        if len(payload) < length:
            logger.warning("autopsy: truncated msgpack frame body")
            break
        try:
            decoded = msgspec.msgpack.decode(payload)
        except Exception:
            logger.warning("autopsy: skipping malformed msgpack frame", exc_info=True)
            continue
        if isinstance(decoded, dict):
            yield decoded


def detect_session_event_encoding(session_dir: Path) -> EventEncoding:
    """Infer encoding from manifest extra or on-disk event files."""
    manifest_path = session_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            extra = manifest.get("extra") or {}
            if isinstance(extra, dict):
                enc = extra.get("event_encoding")
                if enc in ("json", "msgspec"):
                    return enc
        except Exception:
            pass
    if (session_dir / _MSGPACK_GZ).exists() or (session_dir / _MSGPACK_PLAIN).exists():
        return "msgspec"
    return "json"


def resolve_events_path(session_dir: Path, encoding: EventEncoding) -> Path | None:
    if encoding == "msgspec":
        gz = session_dir / _MSGPACK_GZ
        plain = session_dir / _MSGPACK_PLAIN
    else:
        gz = session_dir / _JSON_GZ
        plain = session_dir / _JSON_PLAIN
    if gz.exists():
        return gz
    if plain.exists():
        return plain
    return None


def load_session_event_dicts(session_dir: Path) -> list[dict[str, Any]]:
    """Load all event dicts for a v1 session directory (json or msgpack)."""
    encoding = detect_session_event_encoding(session_dir)
    path = resolve_events_path(session_dir, encoding)
    if path is None:
        return []
    out: list[dict[str, Any]] = []
    if encoding == "msgspec":
        opener = gzip.open if path.suffix == ".gz" or path.name.endswith(".gz") else open
        mode = "rb"
        with opener(path, mode) as f:  # type: ignore[call-overload]
            out.extend(_iter_msgpack_dicts(f))
        return out
    opener = gzip.open if path.suffix == ".gz" or path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:  # type: ignore[call-overload]
        out.extend(_iter_jsonl_dicts(f))
    return out


def events_plain_name(encoding: EventEncoding) -> str:
    return _MSGPACK_PLAIN if encoding == "msgspec" else _JSON_PLAIN


def events_gz_name(encoding: EventEncoding) -> str:
    return _MSGPACK_GZ if encoding == "msgspec" else _JSON_GZ
