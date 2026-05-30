"""Unified autopsy configuration (capture + diagnose + server/demo)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from autopsy.core.config import LensConfig, load_config_from_env as load_lens_config_from_env
from autopsy.diagnostics.config import DiagnoseConfig, load_diagnose_config_from_env


def _parse_bool(raw: str, default: bool) -> bool:
    raw = raw.strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


@dataclass
class AutopsyConfig:
    """Single configuration object for library users."""

    capture: LensConfig = field(default_factory=LensConfig)
    diagnose: DiagnoseConfig = field(default_factory=DiagnoseConfig)
    server_host: str = "127.0.0.1"
    server_port: int = 7823
    demo_enabled: bool = False


def load_config(base: AutopsyConfig | None = None) -> AutopsyConfig:
    """Load capture, diagnose, server, and demo settings from environment."""
    cfg = base or AutopsyConfig()
    cfg.capture = load_lens_config_from_env(cfg.capture)
    cfg.diagnose = load_diagnose_config_from_env(cfg.diagnose)

    if "AUTOPSY_HOST" in os.environ:
        cfg.server_host = os.environ["AUTOPSY_HOST"]
    if "AUTOPSY_PORT" in os.environ:
        try:
            cfg.server_port = int(os.environ["AUTOPSY_PORT"])
        except ValueError:
            pass
    if "AUTOPSY_DEMO" in os.environ:
        cfg.demo_enabled = _parse_bool(os.environ["AUTOPSY_DEMO"], cfg.demo_enabled)

    return cfg


def demo_enabled() -> bool:
    """Whether hackathon demo routes (fix markers, reset) are active."""
    return load_config().demo_enabled
