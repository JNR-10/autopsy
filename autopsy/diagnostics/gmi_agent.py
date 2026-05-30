"""GMIAgent - diagnoses traces using GMI Cloud (OpenAI-compatible API).

Designed for the hackathon: fast (<2s typical), strong reasoning, free tier.

Defensive design:
- If the API call fails (network, auth), returns a sensible heuristic
  DiagnosisResult derived locally from the bundle so the demo never breaks.
- If the LLM returns invalid JSON, attempts repair, then falls back to heuristics.
- Always returns a DiagnosisResult; never raises.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from autopsy.core.interceptor import restore_tracing, suppress_tracing

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import diagnose_heuristic
from .prompts import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_user_prompt
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.gmi")


def _extract_json(text: str) -> Optional[dict]:
    """Try several strategies to extract a JSON object from an LLM response."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return None


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

            parsed = _extract_json(raw)
            if not parsed:
                logger.warning("GMI returned non-JSON response; using heuristic")
                heuristic.raw_response = raw[:2000]
                return heuristic

            return DiagnosisResult(
                root_cause=str(parsed.get("root_cause", heuristic.root_cause))[:1500],
                affected_node_id=str(parsed.get(
                    "affected_node_id", heuristic.affected_node_id)),
                affected_node_name=str(parsed.get(
                    "affected_node_name", heuristic.affected_node_name)),
                error_category=str(parsed.get(
                    "error_category", heuristic.error_category)),
                fix_suggestion=str(parsed.get(
                    "fix_suggestion", heuristic.fix_suggestion))[:2000],
                fix_code_snippet=str(parsed.get("fix_code_snippet", ""))[:3000],
                confidence=float(parsed.get("confidence", 0.7) or 0.7),
                latency_insight=str(parsed.get("latency_insight", ""))[:1000],
                estimated_latency_savings_ms=float(
                    parsed.get("estimated_latency_savings_ms", 0) or 0),
                model_swap_suggestion=str(
                    parsed.get("model_swap_suggestion", ""))[:500],
                raw_response=raw[:4000],
            )
        except Exception:
            logger.exception("autopsy: GMI diagnose failed; using heuristic")
            return heuristic
        finally:
            restore_tracing(token)


# Backward compat for imports of _heuristic_diagnosis
_heuristic_diagnosis = diagnose_heuristic
