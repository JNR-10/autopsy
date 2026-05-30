"""Unit tests for the default redactor."""
from __future__ import annotations

from autopsy.core.events_v2 import EventKind, LLMRequestEvent, LogEvent
from autopsy.core.redact import default_redactor, scrub_secrets


def _llm(messages, **extra):
    return LLMRequestEvent(
        event_id="01HXY000000000000000000001",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=1,
        kind=EventKind.LLM_REQUEST,
        model="m",
        messages=messages,
        attributes=extra,
    )


def test_scrubs_openai_style_keys():
    out = scrub_secrets("Authorization: sk-abcd1234efgh5678ijkl9012mnop3456")
    assert "sk-abcd1234efgh5678ijkl9012mnop3456" not in out
    assert "[REDACTED:secret]" in out


def test_scrubs_bearer_token():
    out = scrub_secrets("Bearer eyJhbGciOi.JhdGUiOiJzZWNyZX.QifQ.signature123")
    assert "eyJhbG" not in out
    assert "[REDACTED:secret]" in out


def test_scrubs_aws_access_key():
    out = scrub_secrets("AWS=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_passes_through_non_secret_strings():
    s = "hello world, my user_id is 12345"
    assert scrub_secrets(s) == s


def test_default_redactor_walks_attributes():
    ev = _llm(messages=[], my_secret="sk-deadbeefdeadbeefdeadbeefdeadbeef")
    out = default_redactor(ev)
    assert out is not None
    assert "sk-deadbeefdeadbeefdeadbeefdeadbeef" not in out.model_dump_json()


def test_default_redactor_walks_messages():
    ev = _llm(messages=[{"role": "u", "content": "key=sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}])
    out = default_redactor(ev)
    assert out is not None
    assert "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in out.model_dump_json()


def test_default_redactor_returns_event_unchanged_when_safe():
    ev = LogEvent(
        event_id="01HXY000000000000000000001",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=1,
        kind=EventKind.LOG,
        name="ok",
        attributes={"safe": "no secrets here"},
    )
    out = default_redactor(ev)
    assert out is not None
    assert out.attributes["safe"] == "no secrets here"
