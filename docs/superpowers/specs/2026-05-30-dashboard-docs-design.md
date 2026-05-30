# Dashboard Cleanup & Production Docs

**Status:** Approved  
**Date:** 2026-05-30  
**Author:** brainstormed with the project lead  
**Sub-project:** 5 of 5 (final roadmap item)

## Purpose

Sub-projects #1–#4 made capture, detectors, CLI, and diagnose providers production-grade. Sub-project #5 **fixes the dashboard for v1 sessions**, surfaces **detector verdicts**, and delivers **production documentation** so users can adopt autopsy without hackathon-era assumptions.

## Goal

- Dashboard session delete/clear works against **v1 session directories** (not v0 JSON blobs only).
- Dashboard shows **detector failures** in session list and session detail.
- Server uses **`autopsy.__version__`**; diagnose UI is provider-agnostic.
- **README** and **`.env.example`** reflect CLI-first workflow, optional diagnose extras, and current architecture.
- Remove dead **`autopsy/deploy`** package stub from setuptools.

## Non-goals

- React dashboard rebuild (vanilla JS fallback stays).
- Removing demo endpoints (`/api/demo/*`) — they support `examples/` live-loop demo.
- PyPI publish automation.

## Constraints

- Dashboard continues consuming **`LegacyBundleReader`** / REST bundle shape.
- Demo commands (`autopsy run`, `autopsy serve`) remain.
- Tests: unit + integration for server delete and list enrichment.

## Changes

### Server session management

Replace v0-only `DELETE /api/sessions` and `DELETE /api/sessions/{id}` with `LocalFilesystemStore`:

- `keep_live=1` preserves sessions whose manifest status is `live` or summary status is `running`.
- Deletes v1 dirs via `store.delete_session()`; also removes legacy v0 `*.json` blobs.
- Reindex not required after bulk delete (store handles index).

### Dashboard UI

- Session sidebar: show detector name when `error_type` starts with `detector:`.
- Session center panel: **Detector verdicts** section (name, verdict, reason) parsed from bundle events.
- Diagnose loading copy: generic "Diagnosing…" (not GMI-specific).
- Fix session list to read nested `summary` fields when flat fields absent.

### Docs

- README: current architecture, CLI as primary surface, `pip install autopsy[diagnose]`, config tables, updated test count.
- `.env.example`: capture + detector + diagnose env vars.

### Packaging

- Drop `autopsy.deploy` from setuptools `include` (module stays empty, not shipped).

## Testing

| Area | Unit | Integration |
|------|------|-------------|
| Server delete v1 | helper logic | DELETE clears v1 dir, keep_live preserves live |
| List enrichment | compat list fields | dashboard API sessions include error_type |
| Docs | — | manual review |

## Success criteria

- Dashboard "clear" button deletes finished v1 sessions.
- Detector-fail session shows verdict in dashboard center panel.
- README accurate; no references to deleted `tracer.py`.
- Full test suite green.
