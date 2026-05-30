"""Diagnose provider protocol and factory."""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import HeuristicProvider
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.provider")


@runtime_checkable
class DiagnoseProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def diagnose(
        self,
        bundle: dict[str, Any],
        target_node_id: str | None = None,
    ) -> DiagnosisResult: ...


def _heuristic_fallback(reason: str) -> HeuristicProvider:
    logger.debug("autopsy: using heuristic provider (%s)", reason)
    return HeuristicProvider()


def _gmi_provider(config: DiagnoseConfig) -> DiagnoseProvider:
    if not config.gmi_api_key:
        return _heuristic_fallback("GMI_API_KEY not set")
    try:
        import openai  # noqa: F401
    except ImportError:
        return _heuristic_fallback("openai package not installed")
    from .gmi_agent import GMIAgent

    return GMIAgent(config=config)


def _gemini_provider(config: DiagnoseConfig) -> DiagnoseProvider:
    if not config.google_ai_api_key:
        return _heuristic_fallback("GOOGLE_AI_API_KEY not set")
    try:
        import google.generativeai  # noqa: F401
    except ImportError:
        return _heuristic_fallback("google-generativeai package not installed")
    from .gemini_agent import GeminiAgent

    return GeminiAgent(config=config)


def resolve_diagnose_provider(
    config: DiagnoseConfig | None = None,
    *,
    model_choice: str | None = None,
    bundle: dict[str, Any] | None = None,
) -> DiagnoseProvider:
    """Select a diagnose provider for CLI/server use."""
    cfg = config or load_diagnose_config_from_env()
    choice = (model_choice or cfg.default_model).strip().lower()

    if choice == "heuristic":
        return HeuristicProvider()
    if choice == "gmi":
        return _gmi_provider(cfg)
    if choice == "gemini":
        return _gemini_provider(cfg)

    # auto: large bundles prefer Gemini, else GMI; each may fall back to heuristic.
    if bundle is not None:
        from .gemini_agent import estimate_bundle_tokens

        est = estimate_bundle_tokens(bundle)
        if est > cfg.auto_token_threshold:
            return _gemini_provider(cfg)
    return _gmi_provider(cfg)
