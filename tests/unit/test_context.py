"""Tests for the capture-layer ContextVars."""
from __future__ import annotations

from autopsy.core.context import (
    current_parent_id,
    current_session,
    is_diagnostics_call,
    set_diagnostics_call,
    set_parent_id,
    set_session,
)


def test_session_default_is_none():
    assert current_session() is None


def test_set_and_reset_session():
    token = set_session("S1")
    assert current_session() == "S1"
    set_session(None, token=token)
    assert current_session() is None


def test_parent_id_default_is_none():
    assert current_parent_id() is None


def test_set_and_reset_parent_id():
    token = set_parent_id("p1")
    assert current_parent_id() == "p1"
    set_parent_id(None, token=token)
    assert current_parent_id() is None


def test_diagnostics_call_default():
    assert is_diagnostics_call() is False


def test_diagnostics_call_set_and_reset():
    token = set_diagnostics_call(True)
    assert is_diagnostics_call() is True
    set_diagnostics_call(False, token=token)
    assert is_diagnostics_call() is False
