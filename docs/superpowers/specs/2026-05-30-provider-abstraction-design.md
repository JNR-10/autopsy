# Provider Abstraction & Packaging Hygiene

**Status:** Approved  
**Date:** 2026-05-30  
**Author:** brainstormed with the project lead  
**Sub-project:** 4 of 5 (see Roadmap section)

## Purpose

Sub-projects #1–#3 made capture, failure detection, and CLI diagnose UX trustworthy. Sub-project #4 **separates diagnose configuration from capture**, introduces a **pluggable provider abstraction**, **deduplicates provider selection** (CLI + server), and **cleans up packaging** so `pip install autopsy` does not hard-require sponsor SDKs.

## Goal

- `DiagnoseConfig` dataclass + env loader (fields removed from `LensConfig` in sub-project #1).
- `DiagnoseProvider` protocol + registry/factory used by CLI and server.
- Three built-in providers: `heuristic`, `gmi`, `gemini` (existing agent logic preserved).
- Optional dependencies: `openai` (GMI), `google-generativeai` (Gemini); core install works with heuristic-only diagnose.
- GitHub Actions CI (pytest + ruff) and aligned semver (`0.2.0`).

## Non-goals (explicitly out of scope)

- Dashboard UI changes — sub-project #5.
- New LLM providers beyond GMI/Gemini/heuristic.
- Rewriting diagnosis prompts or `DiagnosisResult` schema.
- Remote/cloud session backends.
- PyPI publish automation (CI only; manual release is fine for now).

## Constraints

- **Never crash** on missing API keys or optional deps — fall back to heuristic (existing behavior).
- **Single selection path** — `_make_diagnose_agent` in CLI and inline logic in `server/app.py` must call the same factory.
- **Backward compat** — CLI `--model auto|gmi|gemini` and server `force_model` field unchanged.
- **Tests mandatory** — unit + integration per seam (lesson from tool_loop registry bug).

## Architecture

```
DiagnoseConfig (env: AUTOPSY_DIAGNOSE_*, GMI_*, GOOGLE_AI_*)
        │
        ▼
resolve_diagnose_provider(config, model_choice, bundle)
        │
        ├── heuristic  (always available, no SDK)
        ├── gmi        (requires openai extra + GMI_API_KEY)
        └── gemini     (requires google extra + GOOGLE_AI_API_KEY)

CLI cmd_diagnose ──┐
                   ├──► provider.diagnose(bundle, node_id) ──► DiagnosisResult
Server /diagnose ──┘
```

### DiagnoseConfig fields

| Field | Default | Env var(s) |
|-------|---------|------------|
| `default_model` | `"auto"` | `AUTOPSY_DIAGNOSE_MODEL` |
| `auto_token_threshold` | `32000` | `AUTOPSY_DIAGNOSE_TOKEN_THRESHOLD` |
| `gmi_api_key` | `""` | `GMI_API_KEY` |
| `gmi_base_url` | GMI default | `GMI_BASE_URL` |
| `gmi_model` | DeepSeek default | `GMI_DEFAULT_MODEL` |
| `gmi_fallback_model` | Qwen default | `GMI_FALLBACK_MODEL` |
| `gmi_timeout_s` | `10.0` | `AUTOPSY_GMI_TIMEOUT` |
| `google_ai_api_key` | `""` | `GOOGLE_AI_API_KEY` |
| `gemini_model` | `gemini-2.5-pro` | `GEMINI_MODEL` |
| `gemini_timeout_s` | `60.0` | `AUTOPSY_GEMINI_TIMEOUT` |

Removed from capture layer (already gone): `port`, `auto_diagnose` — server port stays on uvicorn CLI; no `auto_diagnose` flag (diagnose is on-demand only).

### DiagnoseProvider protocol

```python
class DiagnoseProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def diagnose(
        self, bundle: dict[str, Any], target_node_id: str | None = None
    ) -> DiagnosisResult: ...
```

Built-in names: `"heuristic"`, `"gmi"`, `"gemini"`.

### Provider selection (`model_choice`)

| `model_choice` | Provider |
|----------------|----------|
| `"heuristic"` | HeuristicProvider |
| `"gmi"` | GMIProvider (or heuristic if no key / no openai) |
| `"gemini"` | GeminiProvider (or heuristic if no key / no google SDK) |
| `"auto"` | Gemini if `estimate_bundle_tokens(bundle) > threshold` else GMI; each falls back to heuristic per above |

Factory returns the **effective** provider (may differ from requested when falling back).

### Optional dependencies

```toml
[project.optional-dependencies]
gmi = ["openai>=1.30.0"]
gemini = ["google-generativeai>=0.7.0"]
diagnose = ["openai>=1.30.0", "google-generativeai>=0.7.0"]
```

Remove `openai` and `google-generativeai` from core `dependencies`. Keep `tiktoken` in core (used by token estimation, no sponsor tie).

Install guidance:
- `pip install autopsy` — capture + CLI + heuristic diagnose
- `pip install autopsy[diagnose]` — full LLM diagnose

### Module layout

```
autopsy/diagnostics/
  config.py          # NEW — DiagnoseConfig + load_diagnose_config_from_env
  provider.py        # NEW — Protocol, HeuristicProvider, factory
  heuristic.py       # NEW — extract _heuristic_diagnosis from gmi_agent
  gmi_agent.py       # MODIFY — use DiagnoseConfig; delegate heuristic import
  gemini_agent.py    # MODIFY — use DiagnoseConfig
  types.py           # unchanged
  prompts.py         # unchanged
autopsy/cli/main.py  # MODIFY — factory instead of _make_diagnose_agent
autopsy/server/app.py # MODIFY — factory
.github/workflows/ci.yml  # NEW
pyproject.toml       # MODIFY — optional deps, version 0.2.0
```

Legacy aliases: `GMIAgent` / `GeminiAgent` remain importable; they become thin wrappers around providers or accept `DiagnoseConfig`.

## Testing strategy (mandatory)

| Seam | Unit | Integration |
|------|------|-------------|
| DiagnoseConfig + env | field defaults, env parsing | — |
| HeuristicProvider | category branches | CLI `--model` path with monkeypatched factory |
| resolve_diagnose_provider | auto threshold, force gmi/gemini, missing keys | server `/diagnose` uses factory |
| Optional deps | ImportError → heuristic | — |
| CLI wiring | mock provider | existing `test_diagnose.py` updated to patch factory |
| Server wiring | — | `test_full_diagnose_replay_flow` still passes |

**CI gate:** `.venv/bin/python -m pytest tests/ -q` and `ruff check autopsy tests`.

## Roadmap context

1. Capture layer ✅  
2. Failure detection ✅  
3. CLI diagnose UX ✅  
4. **Provider abstraction + packaging** ← this spec  
5. Demo/dashboard cleanup + production docs

## Success criteria

- Zero duplicated provider-selection logic outside `resolve_diagnose_provider`.
- `pip install autopsy` succeeds without openai/google-generativeai installed; diagnose returns heuristic result.
- Full test suite green; new tests cover config, factory, and wiring.
- GitHub Actions runs on push/PR.
