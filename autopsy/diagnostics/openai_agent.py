"""OpenAI diagnose provider (also works with OpenAI-compatible endpoints)."""
from __future__ import annotations

import logging
from typing import Any

from autopsy.core.interceptor import restore_tracing, suppress_tracing

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import diagnose_heuristic
from .parsing import diagnosis_from_parsed, extract_json
from .prompts import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_user_prompt
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.openai")


class OpenAIAgent:
    @property
    def name(self) -> str:
        return "openai"

    def __init__(self, config: DiagnoseConfig | None = None):
        cfg = config or load_diagnose_config_from_env()
        self.api_key = cfg.openai_api_key
        self.model = cfg.openai_model
        self.base_url = cfg.openai_base_url
        self.timeout = cfg.openai_timeout_s

    async def diagnose(
        self,
        bundle: dict[str, Any],
        target_node_id: str | None = None,
    ) -> DiagnosisResult:
        heuristic = diagnose_heuristic(bundle, target_node_id)
        if not self.api_key:
            logger.warning("autopsy: OPENAI_API_KEY not set; using heuristic")
            return heuristic
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.warning("autopsy: openai package not installed; using heuristic")
            return heuristic

        user_prompt = build_diagnosis_user_prompt(bundle, target_node_id)
        token = suppress_tracing()
        try:
            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "timeout": self.timeout,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            client = AsyncOpenAI(**kwargs)
            completion = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=900,
            )
            raw = completion.choices[0].message.content or ""
            parsed = extract_json(raw)
            if not parsed:
                heuristic.raw_response = raw[:2000]
                return heuristic
            return diagnosis_from_parsed(parsed, heuristic, raw=raw)
        except Exception:
            logger.exception("autopsy: OpenAI diagnose failed; using heuristic")
            return heuristic
        finally:
            restore_tracing(token)
