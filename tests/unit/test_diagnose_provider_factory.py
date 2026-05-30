"""Tests for resolve_diagnose_provider factory."""
from __future__ import annotations

from autopsy.diagnostics.config import DiagnoseConfig
from autopsy.diagnostics.heuristic import HeuristicProvider
from autopsy.diagnostics.provider import resolve_diagnose_provider


def test_resolve_heuristic_explicit():
    provider = resolve_diagnose_provider(
        DiagnoseConfig(),
        model_choice="heuristic",
    )
    assert isinstance(provider, HeuristicProvider)
    assert provider.name == "heuristic"


def test_resolve_gmi_without_key_falls_back():
    provider = resolve_diagnose_provider(
        DiagnoseConfig(gmi_api_key=""),
        model_choice="gmi",
    )
    assert isinstance(provider, HeuristicProvider)


def test_resolve_gmi_with_key():
    cfg = DiagnoseConfig(gmi_api_key="sk-test")
    provider = resolve_diagnose_provider(cfg, model_choice="gmi")
    assert provider.name == "gmi"


def test_resolve_gemini_without_key_falls_back():
    provider = resolve_diagnose_provider(
        DiagnoseConfig(google_ai_api_key=""),
        model_choice="gemini",
    )
    assert isinstance(provider, HeuristicProvider)


def test_resolve_auto_small_bundle_uses_gmi_path():
    cfg = DiagnoseConfig(gmi_api_key="sk-test")
    bundle = {"events": [{"event_type": "node_start", "node_id": "x"}]}
    provider = resolve_diagnose_provider(cfg, model_choice="auto", bundle=bundle)
    assert provider.name == "gmi"


def test_resolve_auto_large_bundle_uses_gemini_path():
    cfg = DiagnoseConfig(
        google_ai_api_key="google-key",
        auto_token_threshold=100,
    )
    big_events = [{"event_type": "log", "message": "x" * 500}] * 10
    bundle = {"events": big_events}
    provider = resolve_diagnose_provider(cfg, model_choice="auto", bundle=bundle)
    assert provider.name == "gemini"


def test_resolve_auto_respects_token_threshold():
    cfg = DiagnoseConfig(
        gmi_api_key="sk-test",
        auto_token_threshold=1_000_000,
    )
    big_events = [{"event_type": "log", "message": "x" * 500}] * 10
    bundle = {"events": big_events}
    provider = resolve_diagnose_provider(cfg, model_choice="auto", bundle=bundle)
    assert provider.name == "gmi"
