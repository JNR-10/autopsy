"""Ollama local LLM diagnose provider (HTTP, no extra SDK)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from autopsy.core.interceptor import restore_tracing, suppress_tracing

from .config import DiagnoseConfig, load_diagnose_config_from_env
from .heuristic import diagnose_heuristic
from .parsing import diagnosis_from_parsed, extract_json
from .prompts import DIAGNOSIS_SYSTEM_PROMPT, build_diagnosis_user_prompt
from .types import DiagnosisResult

logger = logging.getLogger("autopsy.diagnostics.ollama")


class OllamaAgent:
    @property
    def name(self) -> str:
        return "ollama"

    def __init__(self, config: DiagnoseConfig | None = None):
        cfg = config or load_diagnose_config_from_env()
        self.base_url = cfg.ollama_base_url.rstrip("/")
        self.model = cfg.ollama_model
        self.timeout = cfg.ollama_timeout_s

    async def diagnose(
        self,
        bundle: dict[str, Any],
        target_node_id: str | None = None,
    ) -> DiagnosisResult:
        heuristic = diagnose_heuristic(bundle, target_node_id)
        user_prompt = build_diagnosis_user_prompt(bundle, target_node_id)
        token = suppress_tracing()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            raw = str(data.get("message", {}).get("content", ""))
            parsed = extract_json(raw)
            if not parsed:
                heuristic.raw_response = raw[:2000]
                return heuristic
            return diagnosis_from_parsed(parsed, heuristic, raw=raw)
        except Exception:
            logger.exception("autopsy: Ollama diagnose failed; using heuristic")
            return heuristic
        finally:
            restore_tracing(token)
