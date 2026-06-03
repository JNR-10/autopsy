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
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from autopsy.detectors.defaults import DEFAULT_ENABLED_DETECTORS

logger = logging.getLogger("autopsy.config")


@dataclass
class LensConfig:
    session_dir: str | None = None

    default_sample: str | float = "errors"
    flush_batch_size: int = 100
    flush_interval_ms: int = 50
    writer_spill_batch_events: int = 64
    writer_spill_interval_ms: int = 250
    queue_maxsize: int = 10_000
    max_total_disk_mb: int = 2048
    max_session_age_days: int = 30
    max_in_flight_buffer_mb: int = 10
    max_event_field_bytes: int = 65_536
    log_finalization: bool = True
    log_finalization_info_rate_s: int = 60
    redactor: Callable[[Any], Any] | None = field(default=None)
    enabled_detectors: list[str] = field(
        default_factory=lambda: list(DEFAULT_ENABLED_DETECTORS),
    )
    promote_on_warn: bool = False
    max_capture_buffer_events: int = 1024
    max_capture_buffer_bytes: int = 8_388_608
    tool_loop_threshold: int = 5
    max_tool_calls: int = 50
    latency_threshold_ms: int = 30_000
    duplicate_tool_threshold: int = 3
    error_storm_threshold: int = 3
    detector_full_trace: bool = False
    max_detector_ring_events: int = 8192
    max_detector_eval_events: int = 8192


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
    if "AUTOPSY_PRODUCTION_ALERTING" in os.environ and _parse_bool(
        os.environ["AUTOPSY_PRODUCTION_ALERTING"], False,
    ):
        from autopsy.detectors.presets import apply_production_alerting

        apply_production_alerting(c)
    if "AUTOPSY_DETECTOR_PROFILE" in os.environ:
        from autopsy.detectors.profiles import apply_profile_to_lens_config, get_profile

        prof = get_profile(os.environ["AUTOPSY_DETECTOR_PROFILE"])
        if prof is not None:
            apply_profile_to_lens_config(c, prof)
        else:
            logger.warning(
                "autopsy: unknown AUTOPSY_DETECTOR_PROFILE=%r (strict|balanced|lenient)",
                os.environ["AUTOPSY_DETECTOR_PROFILE"],
            )
    if "AUTOPSY_SAMPLE" in os.environ:
        c.default_sample = _parse_sample(os.environ["AUTOPSY_SAMPLE"])
    if "AUTOPSY_LOG_FINALIZATION" in os.environ:
        c.log_finalization = _parse_bool(
            os.environ["AUTOPSY_LOG_FINALIZATION"], c.log_finalization
        )
    if "AUTOPSY_SESSION_DIR" in os.environ:
        c.session_dir = os.environ["AUTOPSY_SESSION_DIR"]
    if "AUTOPSY_DETECTORS" in os.environ:
        raw = os.environ["AUTOPSY_DETECTORS"].strip()
        if raw.lower() in ("", "off", "none"):
            c.enabled_detectors = []
        else:
            c.enabled_detectors = [x.strip() for x in raw.split(",") if x.strip()]
    if "AUTOPSY_PROMOTE_ON_WARN" in os.environ:
        c.promote_on_warn = _parse_bool(os.environ["AUTOPSY_PROMOTE_ON_WARN"], c.promote_on_warn)
    for env_key, attr in (
        ("AUTOPSY_FLUSH_BATCH_SIZE", "flush_batch_size"),
        ("AUTOPSY_FLUSH_INTERVAL_MS", "flush_interval_ms"),
        ("AUTOPSY_WRITER_SPILL_BATCH_EVENTS", "writer_spill_batch_events"),
        ("AUTOPSY_WRITER_SPILL_INTERVAL_MS", "writer_spill_interval_ms"),
        ("AUTOPSY_QUEUE_MAXSIZE", "queue_maxsize"),
        ("AUTOPSY_MAX_TOTAL_DISK_MB", "max_total_disk_mb"),
        ("AUTOPSY_MAX_SESSION_AGE_DAYS", "max_session_age_days"),
        ("AUTOPSY_MAX_IN_FLIGHT_BUFFER_MB", "max_in_flight_buffer_mb"),
        ("AUTOPSY_MAX_EVENT_FIELD_BYTES", "max_event_field_bytes"),
        ("AUTOPSY_LOG_FINALIZATION_INFO_RATE_S", "log_finalization_info_rate_s"),
        ("AUTOPSY_TOOL_LOOP_THRESHOLD", "tool_loop_threshold"),
        ("AUTOPSY_MAX_TOOL_CALLS", "max_tool_calls"),
        ("AUTOPSY_MAX_CAPTURE_BUFFER_EVENTS", "max_capture_buffer_events"),
        ("AUTOPSY_MAX_CAPTURE_BUFFER_BYTES", "max_capture_buffer_bytes"),
        ("AUTOPSY_LATENCY_THRESHOLD_MS", "latency_threshold_ms"),
        ("AUTOPSY_DUPLICATE_TOOL_THRESHOLD", "duplicate_tool_threshold"),
        ("AUTOPSY_ERROR_STORM_THRESHOLD", "error_storm_threshold"),
        ("AUTOPSY_MAX_DETECTOR_RING_EVENTS", "max_detector_ring_events"),
        ("AUTOPSY_MAX_DETECTOR_EVAL_EVENTS", "max_detector_eval_events"),
    ):
        if env_key in os.environ:
            try:
                setattr(c, attr, int(os.environ[env_key]))
            except ValueError:
                logger.warning("autopsy: invalid %s=%r", env_key, os.environ[env_key])
    if "AUTOPSY_DETECTOR_FULL_TRACE" in os.environ:
        c.detector_full_trace = _parse_bool(
            os.environ["AUTOPSY_DETECTOR_FULL_TRACE"], c.detector_full_trace,
        )
    return c


def default_session_dir() -> Path:
    """Pick a writable session directory (``…/sessions``).

    Order of preference:
      1. AUTOPSY_SESSION_DIR env var (must be writable; created on demand)
      2. ~/.autopsy/sessions (typical user install)
      3. ./.autopsy/sessions (sandbox / read-only home / CI)
      4. /tmp/autopsy_sessions (last resort)
    """
    candidates: list[Path] = []
    raw = os.environ.get("AUTOPSY_SESSION_DIR")
    if raw:
        candidates.append(Path(os.path.expanduser(raw)))
    candidates.append(Path(os.path.expanduser("~/.autopsy/sessions")))
    candidates.append(Path.cwd() / ".autopsy" / "sessions")
    candidates.append(Path(tempfile.gettempdir()) / "autopsy" / "sessions")
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            probe = c / ".write_probe"
            probe.write_text("")
            probe.unlink(missing_ok=True)
            return c
        except Exception:
            continue
    return candidates[-1]
