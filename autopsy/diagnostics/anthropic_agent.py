"""Anthropic Claude diagnose provider."""
from __future__ import annotations

import logging
from typing import Any

from autopsy.core.interceptor import restore_tracing, suppress_tracing

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import diagnose_heuristic
from .parsing import diagnosis_from_parsed, extract_json
from .prompts import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_user_prompt
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.anthropic")


class AnthropicAgent:
    @property
    def name(self) -> str:
        return "anthropic"

    def __init__(self, config: DiagnoseConfig | None = None):
        cfg = config or load_diagnose_config_from_env()
        self.api_key = cfg.anthropic_api_key
        self.model = cfg.anthropic_model
        self.timeout = cfg.anthropic_timeout_s

    async def diagnose(
        self,
        bundle: dict[str, Any],
        target_node_id: str | None = None,
    ) -> DiagnosisResult:
        heuristic = diagnose_heuristic(bundle, target_node_id)
        if not self.api_key:
            logger.warning("autopsy: ANTHROPIC_API_KEY not set; using heuristic")
            return heuristic
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            logger.warning("autopsy: anthropic package not installed; using heuristic")
            return heuristic

        user_prompt = build_diagnosis_user_prompt(bundle, target_node_id)
        token = suppress_tracing()
        try:
            client = AsyncAnthropic(api_key=self.api_key, timeout=self.timeout)
            message = await client.messages.create(
                model=self.model,
                max_tokens=900,
                temperature=0.2,
                system=DIAGNOSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = ""
            for block in message.content:
                if getattr(block, "type", None) == "text":
                    raw += block.text
            parsed = extract_json(raw)
            if not parsed:
                heuristic.raw_response = raw[:2000]
                return heuristic
            return diagnosis_from_parsed(parsed, heuristic, raw=raw)
        except Exception:
            logger.exception("autopsy: Anthropic diagnose failed; using heuristic")
            return heuristic
        finally:
            restore_tracing(token)
