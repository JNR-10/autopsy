"""LoggingExporter — emit one structured log line per session finalize.

WARNING for status in {"error", "partial"}; INFO for "ok" (rate-limited to
one per agent_name per `info_rate_s` seconds so a high-QPS healthy stream
does not flood logs).

Uses LoggerAdapter-style `extra=` so structured-log handlers receive the
fields as keys rather than parsing the human message.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

from ..events import BaseEvent, Manifest

_LOGGER = logging.getLogger("autopsy")


class LoggingExporter:
    def __init__(self, *, info_rate_s: int = 60, enabled: bool = True):
        self.info_rate_s = info_rate_s
        self.enabled = enabled
        self._last_info: dict[str, float] = {}

    def export(self, session_id: str, batch: Iterable[BaseEvent]) -> None:
        return

    def finalize_session(self, manifest: Manifest) -> None:
        if not self.enabled:
            return
        extra = {
            "session_id": manifest.session_id,
            "agent_name": manifest.agent_name,
            "status": manifest.status,
            "error_type": manifest.error_type,
            "duration_ms": manifest.duration_ms,
            "event_count": manifest.event_count,
            "dropped_events": manifest.dropped_events,
            "trace_path": "",
            "autopsy_version": manifest.autopsy_version,
        }
        msg = (
            f"autopsy: agent={manifest.agent_name} status={manifest.status} "
            f"duration={int(manifest.duration_ms or 0)}ms session={manifest.session_id} "
            f"run 'autopsy diagnose {manifest.session_id}' to investigate"
        )
        if manifest.status in ("error", "partial"):
            _LOGGER.warning(msg, extra=extra)
            return
        now = time.monotonic()
        last = self._last_info.get(manifest.agent_name, -1e9)
        if now - last >= self.info_rate_s:
            self._last_info[manifest.agent_name] = now
            _LOGGER.info(msg, extra=extra)
