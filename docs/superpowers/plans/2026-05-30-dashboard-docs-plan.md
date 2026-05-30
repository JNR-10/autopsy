# Dashboard & Production Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** Fix dashboard v1 session management, surface detector verdicts, and ship production README / env docs.

**Spec:** `docs/superpowers/specs/2026-05-30-dashboard-docs-design.md`

---

## Phases (completed in this session)

1. Server delete via `LocalFilesystemStore` + `sessions.py` helpers
2. `LegacyBundleReader.list()` enrichment (error_type, counts)
3. Dashboard JS: detector verdicts, session list fixes, generic diagnose copy
4. README + `.env.example` rewrite; drop `autopsy.deploy` from setuptools
5. Tests: `test_server_session_delete.py`, `test_compat_list_enrichment.py`

**Verify:** `.venv/bin/python -m pytest tests/ -q` && `ruff check autopsy tests`
