"""LensConfig dataclass + environment-variable loader.

This is the single configuration surface for the capture layer. Field
names mirror the spec ("Public API changes" section). Removed fields
from the previous LensConfig (gmi_api_key, google_ai_api_key, port,
auto_diagnose, model) are intentionally absent; they belong to the
diagnose layer and will reappear on a DiagnoseConfig in sub-project #4.

Invariants:
- All fields have sensible defaults so `LensConfig()` is valid.
- Env loader never raises on malformed input; it falls back to defaults
  and logs a warning so a typo in production does not bring the host down.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("autopsy.config")


@dataclass
class LensConfig:
    session_dir: str | None = None

    default_sample: str | float = "errors"
    flush_batch_size: int = 100
    flush_interval_ms: int = 50
    queue_maxsize: int = 10_000
    max_total_disk_mb: int = 2048
    max_session_age_days: int = 30
    max_in_flight_buffer_mb: int = 10
    max_event_field_bytes: int = 65_536
    log_finalization: bool = True
    log_finalization_info_rate_s: int = 60
    redactor: Callable[[Any], Any] | None = field(default=None)


def _parse_sample(raw: str) -> str | float:
    raw = raw.strip().lower()
    if raw in ("all", "errors", "off"):
        return raw
    try:
        f = float(raw)
        if 0.0 <= f <= 1.0:
            return f
    except ValueError:
        pass
    logger.warning("autopsy: invalid AUTOPSY_SAMPLE=%r, falling back to 'errors'", raw)
    return "errors"


def _parse_bool(raw: str, default: bool) -> bool:
    raw = raw.strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


def load_config_from_env(base: LensConfig | None = None) -> LensConfig:
    """Apply AUTOPSY_* env vars on top of `base` (or a fresh default)."""
    c = base or LensConfig()
    if "AUTOPSY_SAMPLE" in os.environ:
        c.default_sample = _parse_sample(os.environ["AUTOPSY_SAMPLE"])
    if "AUTOPSY_LOG_FINALIZATION" in os.environ:
        c.log_finalization = _parse_bool(
            os.environ["AUTOPSY_LOG_FINALIZATION"], c.log_finalization
        )
    if "AUTOPSY_SESSION_DIR" in os.environ:
        c.session_dir = os.environ["AUTOPSY_SESSION_DIR"]
    for env_key, attr in (
        ("AUTOPSY_FLUSH_BATCH_SIZE", "flush_batch_size"),
        ("AUTOPSY_FLUSH_INTERVAL_MS", "flush_interval_ms"),
        ("AUTOPSY_QUEUE_MAXSIZE", "queue_maxsize"),
        ("AUTOPSY_MAX_TOTAL_DISK_MB", "max_total_disk_mb"),
        ("AUTOPSY_MAX_SESSION_AGE_DAYS", "max_session_age_days"),
        ("AUTOPSY_MAX_IN_FLIGHT_BUFFER_MB", "max_in_flight_buffer_mb"),
        ("AUTOPSY_MAX_EVENT_FIELD_BYTES", "max_event_field_bytes"),
        ("AUTOPSY_LOG_FINALIZATION_INFO_RATE_S", "log_finalization_info_rate_s"),
    ):
        if env_key in os.environ:
            try:
                setattr(c, attr, int(os.environ[env_key]))
            except ValueError:
                logger.warning("autopsy: invalid %s=%r", env_key, os.environ[env_key])
    return c
