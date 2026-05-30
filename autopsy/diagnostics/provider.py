"""Diagnose provider protocol and factory."""
from __future__ import annotations

import logging
from typing import Any, Callable, Protocol, runtime_checkable

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import HeuristicProvider
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.provider")

_PROVIDER_NAMES = frozenset({
    "heuristic", "openai", "anthropic", "gmi", "gemini", "ollama", "auto",
})


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


def _openai_provider(config: DiagnoseConfig) -> DiagnoseProvider:
    if not config.openai_api_key:
        return _heuristic_fallback("OPENAI_API_KEY not set")
    try:
        import openai  # noqa: F401
    except ImportError:
        return _heuristic_fallback("openai package not installed")
    from .openai_agent import OpenAIAgent

    return OpenAIAgent(config=config)


def _anthropic_provider(config: DiagnoseConfig) -> DiagnoseProvider:
    if not config.anthropic_api_key:
        return _heuristic_fallback("ANTHROPIC_API_KEY not set")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return _heuristic_fallback("anthropic package not installed")
    from .anthropic_agent import AnthropicAgent

    return AnthropicAgent(config=config)


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
        from google import genai  # noqa: F401
    except ImportError:
        return _heuristic_fallback("google-genai package not installed")
    from .gemini_agent import GeminiAgent

    return GeminiAgent(config=config)


def _ollama_provider(config: DiagnoseConfig) -> DiagnoseProvider:
    from .ollama_agent import OllamaAgent

    return OllamaAgent(config=config)


def _resolve_auto(config: DiagnoseConfig, bundle: dict[str, Any] | None) -> DiagnoseProvider:
    """Pick the best available provider for ``auto`` mode."""
    from .gemini_agent import estimate_bundle_tokens

    est = estimate_bundle_tokens(bundle) if bundle else 0
    if est > config.auto_token_threshold and config.google_ai_api_key:
        provider = _gemini_provider(config)
        if provider.name != "heuristic":
            return provider

    factories: list[Callable[[DiagnoseConfig], DiagnoseProvider]] = [
        _openai_provider,
        _gmi_provider,
        _anthropic_provider,
        _gemini_provider,
        _ollama_provider,
    ]
    for factory in factories:
        provider = factory(config)
        if provider.name != "heuristic":
            return provider
    return HeuristicProvider()


def resolve_diagnose_provider(
    config: DiagnoseConfig | None = None,
    *,
    model_choice: str | None = None,
    bundle: dict[str, Any] | None = None,
) -> DiagnoseProvider:
    """Select a diagnose provider for CLI/server use."""
    cfg = config or load_diagnose_config_from_env()
    choice = (model_choice or cfg.default_model).strip().lower()
    if choice not in _PROVIDER_NAMES:
        logger.warning("autopsy: unknown diagnose model %r, using auto", choice)
        choice = "auto"

    if choice == "heuristic":
        return HeuristicProvider()
    if choice == "openai":
        return _openai_provider(cfg)
    if choice == "anthropic":
        return _anthropic_provider(cfg)
    if choice == "gmi":
        return _gmi_provider(cfg)
    if choice == "gemini":
        return _gemini_provider(cfg)
    if choice == "ollama":
        return _ollama_provider(cfg)
    return _resolve_auto(cfg, bundle)
