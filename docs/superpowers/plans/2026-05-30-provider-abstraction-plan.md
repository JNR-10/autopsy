# Provider Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `DiagnoseConfig`, a `DiagnoseProvider` protocol with heuristic/GMI/Gemini implementations, a unified factory for CLI + server, optional SDK dependencies, and GitHub Actions CI.

**Architecture:** Diagnose settings live in `autopsy/diagnostics/config.py`. Provider selection is centralized in `resolve_diagnose_provider()`. Existing agent classes remain but consume `DiagnoseConfig` and import heuristic logic from `heuristic.py`. Packaging moves sponsor SDKs to optional extras.

**Tech Stack:** Python 3.11+, pytest, ruff, optional openai + google-generativeai.

---

## Spec

Full design: `docs/superpowers/specs/2026-05-30-provider-abstraction-design.md`. If this plan disagrees with the spec, the spec wins.

## Phases

1. **DiagnoseConfig** — dataclass + env loader + unit tests.
2. **Heuristic extract** — `heuristic.py` + `HeuristicProvider`.
3. **Provider protocol + factory** — `provider.py` + selection logic tests.
4. **Refactor agents** — GMI/Gemini use config; lazy optional imports.
5. **Wire CLI + server** — replace duplicated selection.
6. **Packaging** — optional deps, version 0.2.0, setuptools packages.
7. **CI + integration** — GitHub Actions, wiring integration tests, green sweep.

Each task is TDD where applicable. User commits manually unless asked.

## Conventions

- Run tests: `.venv/bin/python -m pytest <path> -v`
- Lint: `.venv/bin/ruff check autopsy tests`
- Commit style: `feat(diagnostics): …`, `test(diagnostics): …`, `chore(ci): …`

## File structure

```
autopsy/diagnostics/
  config.py
  heuristic.py
  provider.py
  gmi_agent.py       # MODIFY
  gemini_agent.py    # MODIFY
tests/unit/
  test_diagnose_config.py
  test_heuristic_provider.py
  test_diagnose_provider_factory.py
tests/integration/
  test_diagnose_provider_wiring.py
.github/workflows/ci.yml
pyproject.toml       # MODIFY
autopsy/cli/main.py  # MODIFY
autopsy/server/app.py # MODIFY
```

---

## Phase 1 — DiagnoseConfig

### Task 1.1: DiagnoseConfig fields + env loader

**Files:**
- Create: `autopsy/diagnostics/config.py`
- Test: `tests/unit/test_diagnose_config.py`

- [ ] **Step 1: Write failing tests** — defaults, `GMI_API_KEY`, `AUTOPSY_DIAGNOSE_MODEL`, token threshold.
- [ ] **Step 2: Run** — expect import/attribute failures.
- [ ] **Step 3: Implement** `DiagnoseConfig` + `load_diagnose_config_from_env()` mirroring `LensConfig` patterns (never raise on bad env).
- [ ] **Step 4: Green** — `pytest tests/unit/test_diagnose_config.py -v`
- [ ] **Step 5: Commit** — `feat(diagnostics): add DiagnoseConfig and env loader`

---

## Phase 2 — Heuristic extract

### Task 2.1: Move heuristic to dedicated module

**Files:**
- Create: `autopsy/diagnostics/heuristic.py`
- Modify: `autopsy/diagnostics/gmi_agent.py` (import from heuristic)
- Test: `tests/unit/test_heuristic_provider.py`

- [ ] **Step 1: Test** — heuristic returns `DiagnosisResult` for JSON error bundle.
- [ ] **Step 2: Extract** `_heuristic_diagnosis` → `heuristic.diagnose_heuristic()`.
- [ ] **Step 3: HeuristicProvider** class in `provider.py` (or heuristic.py).
- [ ] **Step 4: Green + commit** — `refactor(diagnostics): extract heuristic provider`

---

## Phase 3 — Provider factory

### Task 3.1: Protocol + resolve_diagnose_provider

**Files:**
- Create: `autopsy/diagnostics/provider.py`
- Test: `tests/unit/test_diagnose_provider_factory.py`

Tests to cover:
- `model_choice="heuristic"` → HeuristicProvider
- `model_choice="gmi"` with key → GMI provider name
- `model_choice="gmi"` without key → heuristic fallback
- `model_choice="auto"` small bundle → gmi path; large bundle → gemini path
- `auto_token_threshold` override via config

- [ ] **Step 1–5: TDD cycle + commit** — `feat(diagnostics): add diagnose provider factory`

---

## Phase 4 — Refactor agents

### Task 4.1: GMI/Gemini accept DiagnoseConfig

**Files:**
- Modify: `autopsy/diagnostics/gmi_agent.py`, `gemini_agent.py`

- [ ] Pass config fields instead of reading os.environ in `__init__` when config provided.
- [ ] Lazy `import openai` / `google.generativeai` with ImportError → heuristic.
- [ ] Existing agent tests still pass (add unit tests if none exist).
- [ ] Commit — `refactor(diagnostics): agents use DiagnoseConfig`

---

## Phase 5 — Wire CLI + server

### Task 5.1: CLI uses factory

**Files:**
- Modify: `autopsy/cli/main.py`
- Modify: `tests/cli/test_diagnose.py` — patch `resolve_diagnose_provider` instead of `_make_diagnose_agent`

- [ ] Replace `_make_diagnose_agent` with factory call.
- [ ] Keep `_make_diagnose_agent` as deprecated alias or remove if tests updated.
- [ ] Green CLI tests + commit — `feat(cli): use diagnose provider factory`

### Task 5.2: Server uses factory

**Files:**
- Modify: `autopsy/server/app.py`

- [ ] Inline selection → `resolve_diagnose_provider(load_diagnose_config_from_env(), ...)`
- [ ] Commit — `feat(server): use diagnose provider factory`

---

## Phase 6 — Packaging

### Task 6.1: Optional dependencies + version

**Files:**
- Modify: `pyproject.toml`

- [ ] Remove `openai`, `google-generativeai` from core deps.
- [ ] Add `[project.optional-dependencies] gmi`, `gemini`, `diagnose`.
- [ ] Set `version = "0.2.0"` (match `autopsy/__init__.py`).
- [ ] Add `autopsy.diagnostics` to setuptools packages if missing.
- [ ] Commit — `chore(packaging): optional diagnose SDK deps, bump 0.2.0`

---

## Phase 7 — CI + integration

### Task 7.1: GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] Python 3.11 matrix, install `.[dev,diagnose]`, pytest + ruff.
- [ ] Commit — `chore(ci): add GitHub Actions workflow`

### Task 7.2: Wiring integration tests

**Files:**
- Create: `tests/integration/test_diagnose_provider_wiring.py`

- [ ] CLI: real Writer session → diagnose with factory returning known result.
- [ ] Server: POST diagnose returns factory result (monkeypatch).
- [ ] Full suite green — `pytest tests/ -q`
- [ ] Commit — `test(diagnostics): provider wiring integration tests`

---

## Final sweep

- [ ] `ruff check autopsy tests`
- [ ] `pytest tests/ -q` — all green
- [ ] Manual: `autopsy diagnose <id>` without API keys returns heuristic (no ImportError)
