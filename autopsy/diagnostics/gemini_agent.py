"""GeminiAgent - used when traces exceed ~32k tokens.

Uses Google's google-genai SDK. Always falls back to the heuristic
diagnosis if the API is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import diagnose_heuristic
from .parsing import diagnosis_from_parsed, extract_json
from .prompts import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_user_prompt
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.gemini")


class GeminiAgent:
    @property
    def name(self) -> str:
        return "gemini"

    def __init__(
        self,
        config: DiagnoseConfig | None = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        cfg = config or load_diagnose_config_from_env()
        self.api_key = api_key if api_key is not None else cfg.google_ai_api_key
        self.model = model if model is not None else cfg.gemini_model
        self.timeout = timeout if timeout is not None else cfg.gemini_timeout_s

    async def diagnose(
        self, bundle: dict[str, Any], target_node_id: Optional[str] = None
    ) -> DiagnosisResult:
        heuristic = diagnose_heuristic(bundle, target_node_id)
        if not self.api_key:
            logger.warning("autopsy: GOOGLE_AI_API_KEY not set; using heuristic")
            return heuristic
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.warning("autopsy: google-genai not installed; using heuristic")
            return heuristic
        try:
            client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=self.timeout),
            )
            user_prompt = build_diagnosis_user_prompt(bundle, target_node_id)
            resp = await client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=DIAGNOSIS_SYSTEM_PROMPT,
                    temperature=0.2,
                    max_output_tokens=900,
                ),
            )
            raw = resp.text or ""
            parsed = extract_json(raw)
            if not parsed:
                heuristic.raw_response = raw[:2000]
                return heuristic
            return diagnosis_from_parsed(parsed, heuristic, raw=raw)
        except Exception:
            logger.exception("autopsy: Gemini diagnose failed; using heuristic")
            return heuristic


def estimate_bundle_tokens(bundle: dict[str, Any]) -> int:
    """Rough size estimate (chars/4) of the full bundle as text."""
    import json

    try:
        return len(json.dumps(bundle.get("events", []), default=str)) // 4
    except Exception:
        return 0
