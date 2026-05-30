"""Tests for DiagnoseConfig and env parsing."""
from __future__ import annotations

from autopsy.diagnostics.config import DiagnoseConfig, load_diagnose_config_from_env


def test_default_diagnose_config():
    c = DiagnoseConfig()
    assert c.default_model == "auto"
    assert c.auto_token_threshold == 32_000
    assert c.gmi_api_key == ""
    assert c.google_ai_api_key == ""
    assert c.gmi_timeout_s == 10.0
    assert c.gemini_timeout_s == 60.0


def test_env_gmi_api_key(monkeypatch):
    monkeypatch.setenv("GMI_API_KEY", "sk-test")
    c = load_diagnose_config_from_env()
    assert c.gmi_api_key == "sk-test"


def test_env_google_ai_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "google-key")
    c = load_diagnose_config_from_env()
    assert c.google_ai_api_key == "google-key"


def test_env_autopsy_diagnose_model(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DIAGNOSE_MODEL", "gemini")
    c = load_diagnose_config_from_env()
    assert c.default_model == "gemini"


def test_env_autopsy_diagnose_token_threshold(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DIAGNOSE_TOKEN_THRESHOLD", "16000")
    c = load_diagnose_config_from_env()
    assert c.auto_token_threshold == 16_000


def test_env_invalid_token_threshold_falls_back(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DIAGNOSE_TOKEN_THRESHOLD", "not-a-number")
    c = load_diagnose_config_from_env()
    assert c.auto_token_threshold == 32_000


def test_env_gmi_base_url(monkeypatch):
    monkeypatch.setenv("GMI_BASE_URL", "https://custom.example/v1")
    c = load_diagnose_config_from_env()
    assert c.gmi_base_url == "https://custom.example/v1"
