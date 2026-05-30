"""FileSystemExporter — thin wrapper around LocalFilesystemStore.

Exists so the writer's exporter contract is the same as any future
OTel / Sentry adapter. All disk I/O is delegated to the store. Errors
are caught and logged so a failing exporter cannot crash the writer.
"""
from __future__ import annotations

import logging
from typing import Iterable

from ..events import BaseEvent, Manifest

logger = logging.getLogger("autopsy.exporter.file")


class FileSystemExporter:
    def __init__(self, store):
        self.store = store

    def export(self, session_id: str, batch: Iterable[BaseEvent]) -> None:
        try:
            self.store.write_events(session_id, list(batch))
        except Exception:
            logger.exception("autopsy: FileSystemExporter.export failed")

    def finalize_session(self, manifest: Manifest) -> None:
        try:
            self.store.finalize_session(manifest)
        except Exception:
            logger.exception("autopsy: FileSystemExporter.finalize_session failed")
