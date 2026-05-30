"""Exporter Protocol — the seam for fanning events out beyond local disk.

`FileSystemExporter` wraps the LocalFilesystemStore. `LoggingExporter`
emits a structured `logging` line on finalize. Both ship in v1.

Future OpenTelemetry / Sentry / DataDog exporters slot in here without
changing the writer.
"""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from ..events_v2 import BaseEvent, Manifest


@runtime_checkable
class Exporter(Protocol):
    def export(self, session_id: str, batch: Iterable[BaseEvent]) -> None: ...

    def finalize_session(self, manifest: Manifest) -> None: ...
