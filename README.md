# autopsy

> _Your agent died. Here's why._

One decorator. Full agent visibility. Semantic failure detection. CLI-first inspection. Optional AI diagnosis.

`autopsy` wraps async LLM agents with `@lens.trace`, captures execution traces to disk (sampled on error by default), runs built-in failure detectors at session end, and exposes a production CLI for listing, inspecting, diagnosing, and replaying sessions.

## Install

```bash
# Capture + CLI only (production tracing, heuristic diagnose)
pip install autopsy

# Dashboard server
pip install "autopsy[server]"

# LLM-powered diagnose (OpenAI, Anthropic, GMI, Gemini)
pip install "autopsy[diagnose]"

# Everything
pip install "autopsy[server,diagnose]"

# Development
pip install -e ".[dev,server,diagnose]"
```

## Quickstart

```python
from autopsy import lens, log, load_config

cfg = load_config()  # capture + diagnose settings from env

@lens.trace
async def my_agent(query: str):
    log("step", name="fetch")
    ...
```

Record a session and inspect it from the CLI:

```bash
python your_agent.py
autopsy ls
autopsy show <session_id>
autopsy diagnose <session_id> --model auto
```

Optional dashboard (requires `[server]` extra):

```bash
autopsy serve
autopsy run examples/simple_agent.py   # enables demo mode for example scripts
```

## CLI reference

| Command | Purpose |
|---------|---------|
| `autopsy ls` | List sessions (`--json` for scripts) |
| `autopsy show <id>` | Session detail + detector verdicts |
| `autopsy diagnose <id>` | Root-cause analysis (`--model auto\|openai\|anthropic\|gmi\|gemini\|ollama\|heuristic`) |
| `autopsy tail <id>` | Last N events or live NDJSON stream |
| `autopsy export` / `import` | Tarball round-trip |
| `autopsy replay <id>` | Simulated replay with fix |
| `autopsy clean --all` | Delete all local sessions |
| `autopsy serve` / `run` | Dashboard (`[server]` extra required) |

## Diagnose providers

| Provider | Extra | Env vars |
|----------|-------|----------|
| heuristic | core | always available |
| openai | `[diagnose]` or `[openai]` | `OPENAI_API_KEY`, `OPENAI_MODEL` |
| anthropic | `[diagnose]` or `[anthropic]` | `ANTHROPIC_API_KEY` |
| gmi | `[diagnose]` or `[gmi]` | `GMI_API_KEY` |
| gemini | `[diagnose]` or `[gemini]` | `GOOGLE_AI_API_KEY` |
| ollama | core (`httpx`) | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| auto | — | picks best available (Gemini for large traces) |

Without API keys, diagnose falls back to a **local heuristic** — never crashes.

## Configuration

Use `load_config()` for a single config object, or set env vars directly. See `.env.example`.

**Capture:** `AUTOPSY_SAMPLE`, `AUTOPSY_DETECTORS`, `AUTOPSY_SESSION_DIR`, …

**Diagnose:** `AUTOPSY_DIAGNOSE_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …

**Demo:** `AUTOPSY_DEMO=1` enables hackathon demo routes (`/api/demo/*`). Set automatically by `autopsy run`.

## Architecture

```
autopsy/
  core/           # capture: decorator, writer, store, events
  detectors/      # semantic failure detection
  diagnostics/    # pluggable diagnose providers
  cli/            # Click commands
  server/         # optional dashboard ([server] extra)
  demo/           # demo-only routes (AUTOPSY_DEMO=1)
examples/         # demo scripts (not shipped in wheel)
```

Public API: `from autopsy import lens, log, load_config, LensConfig, AutopsyConfig`

## Tests & release

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check autopsy tests
```

CI runs on Python 3.11 and 3.12. See `CHANGELOG.md` for release notes. Publish to PyPI via GitHub Release.

## License

MIT
