"""GMIAgent - diagnoses traces using GMI Cloud (OpenAI-compatible API).

Designed for the hackathon: fast (<2s typical), strong reasoning, free tier.

Defensive design:
- If the API call fails (network, auth), returns a sensible heuristic
  DiagnosisResult derived locally from the bundle so the demo never breaks.
- If the LLM returns invalid JSON, attempts repair, then falls back to heuristics.
- Always returns a DiagnosisResult; never raises.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from autopsy.core.interceptor import restore_tracing, suppress_tracing

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import diagnose_heuristic
from .parsing import diagnosis_from_parsed, extract_json
from .prompts import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_user_prompt
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.gmi")


class GMIAgent:
    @property
    def name(self) -> str:
        return "gmi"

    def __init__(
        self,
        config: DiagnoseConfig | None = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        cfg = config or load_diagnose_config_from_env()
        self.api_key = api_key if api_key is not None else cfg.gmi_api_key
        self.base_url = base_url if base_url is not None else cfg.gmi_base_url
        self.model = model if model is not None else cfg.gmi_model
        self.fallback_model = (
            fallback_model if fallback_model is not None else cfg.gmi_fallback_model
        )
        self.timeout = timeout if timeout is not None else cfg.gmi_timeout_s

    async def diagnose(
        self, bundle: dict[str, Any], target_node_id: Optional[str] = None
    ) -> DiagnosisResult:
        heuristic = diagnose_heuristic(bundle, target_node_id)
        if not self.api_key:
            logger.warning("autopsy: GMI_API_KEY not set; using heuristic diagnosis")
            return heuristic

        user_prompt = build_diagnosis_user_prompt(bundle, target_node_id)

        token = suppress_tracing()
        try:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                logger.warning(
                    "autopsy: openai package not installed; using heuristic diagnosis"
                )
                return heuristic

            client = AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
            )
            try:
                completion = await client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    max_tokens=600,
                )
            except Exception as exc:
                logger.warning("GMI primary model failed (%s), trying fallback", exc)
                try:
                    completion = await client.chat.completions.create(
                        model=self.fallback_model,
                        messages=[
                            {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.2,
                        max_tokens=600,
                    )
                except Exception as exc2:
                    logger.warning("GMI fallback model failed (%s); using heuristic", exc2)
                    heuristic.raw_response = f"GMI API failed: {exc2}"
                    return heuristic

            raw = ""
            try:
                raw = completion.choices[0].message.content or ""
            except Exception:
                pass

            parsed = extract_json(raw)
            if not parsed:
                logger.warning("GMI returned non-JSON response; using heuristic")
                heuristic.raw_response = raw[:2000]
                return heuristic

            return diagnosis_from_parsed(parsed, heuristic, raw=raw)
        except Exception:
            logger.exception("autopsy: GMI diagnose failed; using heuristic")
            return heuristic
        finally:
            restore_tracing(token)


# Backward compat for imports of _heuristic_diagnosis
_heuristic_diagnosis = diagnose_heuristic
