"""DiagnoseConfig dataclass + environment-variable loader."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("autopsy.diagnostics.config")

_DEFAULT_GMI_BASE_URL = "https://api.gmi-serving.com/v1"
_DEFAULT_GMI_MODEL = "deepseek-ai/DeepSeek-V3.2"
_DEFAULT_GMI_FALLBACK = "Qwen/Qwen3-Next-80B-A3B-Instruct"
_DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"
_DEFAULT_OPENAI_MODEL = "gpt-4o"
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
_DEFAULT_OLLAMA_MODEL = "llama3.2"
_DEFAULT_OLLAMA_BASE = "http://localhost:11434"


@dataclass
class DiagnoseConfig:
    default_model: str = "auto"
    auto_token_threshold: int = 32_000

    gmi_api_key: str = ""
    gmi_base_url: str = _DEFAULT_GMI_BASE_URL
    gmi_model: str = _DEFAULT_GMI_MODEL
    gmi_fallback_model: str = _DEFAULT_GMI_FALLBACK
    gmi_timeout_s: float = 10.0

    google_ai_api_key: str = ""
    gemini_model: str = _DEFAULT_GEMINI_MODEL
    gemini_timeout_s: float = 60.0

    openai_api_key: str = ""
    openai_model: str = _DEFAULT_OPENAI_MODEL
    openai_base_url: str | None = None
    openai_timeout_s: float = 60.0

    anthropic_api_key: str = ""
    anthropic_model: str = _DEFAULT_ANTHROPIC_MODEL
    anthropic_timeout_s: float = 60.0

    ollama_base_url: str = _DEFAULT_OLLAMA_BASE
    ollama_model: str = _DEFAULT_OLLAMA_MODEL
    ollama_timeout_s: float = 120.0


def _parse_int(raw: str, default: int, env_name: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "autopsy: invalid %s=%r, falling back to %d",
            env_name,
            raw,
            default,
        )
        return default


def _parse_float(raw: str, default: float, env_name: str) -> float:
    try:
        return float(raw.strip())
    except ValueError:
        logger.warning(
            "autopsy: invalid %s=%r, falling back to %s",
            env_name,
            raw,
            default,
        )
        return default


def load_diagnose_config_from_env(
    base: DiagnoseConfig | None = None,
) -> DiagnoseConfig:
    """Apply diagnose-related env vars on top of `base` (or defaults)."""
    c = base or DiagnoseConfig()

    if "AUTOPSY_DIAGNOSE_MODEL" in os.environ:
        c.default_model = os.environ["AUTOPSY_DIAGNOSE_MODEL"].strip().lower()

    if "AUTOPSY_DIAGNOSE_TOKEN_THRESHOLD" in os.environ:
        c.auto_token_threshold = _parse_int(
            os.environ["AUTOPSY_DIAGNOSE_TOKEN_THRESHOLD"],
            c.auto_token_threshold,
            "AUTOPSY_DIAGNOSE_TOKEN_THRESHOLD",
        )

    if "GMI_API_KEY" in os.environ:
        c.gmi_api_key = os.environ["GMI_API_KEY"]
    if "GMI_BASE_URL" in os.environ:
        c.gmi_base_url = os.environ["GMI_BASE_URL"]
    if "GMI_DEFAULT_MODEL" in os.environ:
        c.gmi_model = os.environ["GMI_DEFAULT_MODEL"]
    if "GMI_FALLBACK_MODEL" in os.environ:
        c.gmi_fallback_model = os.environ["GMI_FALLBACK_MODEL"]
    if "AUTOPSY_GMI_TIMEOUT" in os.environ:
        c.gmi_timeout_s = _parse_float(
            os.environ["AUTOPSY_GMI_TIMEOUT"], c.gmi_timeout_s, "AUTOPSY_GMI_TIMEOUT",
        )

    if "GOOGLE_AI_API_KEY" in os.environ:
        c.google_ai_api_key = os.environ["GOOGLE_AI_API_KEY"]
    if "GEMINI_MODEL" in os.environ:
        c.gemini_model = os.environ["GEMINI_MODEL"]
    if "AUTOPSY_GEMINI_TIMEOUT" in os.environ:
        c.gemini_timeout_s = _parse_float(
            os.environ["AUTOPSY_GEMINI_TIMEOUT"], c.gemini_timeout_s, "AUTOPSY_GEMINI_TIMEOUT",
        )

    if "OPENAI_API_KEY" in os.environ:
        c.openai_api_key = os.environ["OPENAI_API_KEY"]
    if "OPENAI_MODEL" in os.environ:
        c.openai_model = os.environ["OPENAI_MODEL"]
    if "OPENAI_BASE_URL" in os.environ:
        raw = os.environ["OPENAI_BASE_URL"].strip()
        c.openai_base_url = raw or None
    if "AUTOPSY_OPENAI_TIMEOUT" in os.environ:
        c.openai_timeout_s = _parse_float(
            os.environ["AUTOPSY_OPENAI_TIMEOUT"], c.openai_timeout_s, "AUTOPSY_OPENAI_TIMEOUT",
        )

    if "ANTHROPIC_API_KEY" in os.environ:
        c.anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    if "ANTHROPIC_MODEL" in os.environ:
        c.anthropic_model = os.environ["ANTHROPIC_MODEL"]
    if "AUTOPSY_ANTHROPIC_TIMEOUT" in os.environ:
        c.anthropic_timeout_s = _parse_float(
            os.environ["AUTOPSY_ANTHROPIC_TIMEOUT"],
            c.anthropic_timeout_s,
            "AUTOPSY_ANTHROPIC_TIMEOUT",
        )

    if "OLLAMA_BASE_URL" in os.environ:
        c.ollama_base_url = os.environ["OLLAMA_BASE_URL"]
    if "OLLAMA_MODEL" in os.environ:
        c.ollama_model = os.environ["OLLAMA_MODEL"]
    if "AUTOPSY_OLLAMA_TIMEOUT" in os.environ:
        c.ollama_timeout_s = _parse_float(
            os.environ["AUTOPSY_OLLAMA_TIMEOUT"], c.ollama_timeout_s, "AUTOPSY_OLLAMA_TIMEOUT",
        )

    return c
