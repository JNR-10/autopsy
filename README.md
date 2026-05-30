# autopsy

> _Your agent died. Here's why._

One decorator. Full agent visibility. Semantic failure detection. CLI-first inspection. Optional AI diagnosis.

`autopsy` wraps async LLM agents with `@lens.trace`, captures execution traces to disk (sampled on error by default), runs built-in failure detectors at session end, and exposes a production CLI for listing, inspecting, diagnosing, and replaying sessions.

## Install

```bash
pip install autopsy

# Optional: LLM-powered diagnose (GMI + Gemini providers)
pip install "autopsy[diagnose]"

# Development
pip install -e ".[dev,diagnose]"
```

## Quickstart

```python
from autopsy import lens, log

@lens.trace
async def my_agent(query: str):
    log("step", name="fetch")
    ...
```

Record a session and inspect it from the CLI:

```bash
python your_agent.py          # runs with capture enabled via env/decorator
autopsy ls                    # list saved sessions
autopsy show <session_id>     # manifest, detector verdicts, errors
autopsy diagnose <session_id> # AI or heuristic root-cause (--json)
```

Optional dashboard (demo / live viewing):

```bash
autopsy serve                 # http://127.0.0.1:7823
autopsy run examples/simple_agent.py   # serve + run script
```

## CLI reference

| Command | Purpose |
|---------|---------|
| `autopsy ls` | List sessions (`--json` for scripts) |
| `autopsy show <id>` | Session detail + detector verdicts (`--events`, `--json`) |
| `autopsy diagnose <id>` | Root-cause analysis (`--model auto\|gmi\|gemini`, `--json`) |
| `autopsy tail <id>` | Last N events or live NDJSON stream |
| `autopsy export` / `import` | Tarball round-trip (default) or legacy JSON |
| `autopsy replay <id>` | Simulated replay with fix (`--json`) |
| `autopsy clean --all` | Delete all local sessions |
| `autopsy serve` / `run` | Dashboard server (demo convenience) |

## Configuration

Copy `.env.example` to `.env`. Key variables:

**Capture** (`LensConfig` / `AUTOPSY_*`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTOPSY_SESSION_DIR` | auto | Session storage root |
| `AUTOPSY_SAMPLE` | `errors` | `all`, `errors`, `off`, or 0.0–1.0 rate |
| `AUTOPSY_DETECTORS` | all built-ins | Comma list or `off` |
| `AUTOPSY_TOOL_LOOP_THRESHOLD` | `5` | Repeated tool calls before fail |

**Diagnose** (`DiagnoseConfig`):

| Variable | Description |
|----------|-------------|
| `GMI_API_KEY` | GMI Cloud (OpenAI-compatible) |
| `GOOGLE_AI_API_KEY` | Gemini long-context fallback |
| `AUTOPSY_DIAGNOSE_MODEL` | `auto`, `gmi`, `gemini`, or `heuristic` |

Without API keys or optional extras, diagnose falls back to a **local heuristic** — never crashes.

## What you get

- **Non-blocking capture** — bounded queue, writer thread, crash-safe v1 on-disk format
- **Failure detectors** — `empty_response`, `tool_loop`, `missing_output` at session end
- **CLI-first UX** — Rich human output + stable `--json` for automation
- **Pluggable diagnose providers** — heuristic (always), GMI, Gemini (`autopsy[diagnose]`)
- **OpenAI SDK interception** — transparent LLM/tool capture for compatible clients
- **Dashboard** — vanilla-JS live DAG viewer (optional; CLI is the daily driver)
- **Replay engine** — simulated before/after comparison from saved traces

## Architecture

```
autopsy/
  core/           # capture: decorator, writer, store, events, compat reader
  detectors/      # semantic failure detection at session end
  diagnostics/    # DiagnoseConfig, providers (heuristic/gmi/gemini)
  cli/            # Click commands (ls, show, diagnose, …)
  server/         # FastAPI dashboard + WebSocket (optional)
examples/         # demo agents (not shipped in the wheel)
tests/            # unit, integration, perf
```

Public API: `from autopsy import lens, log, LensConfig`

## Demos

**Continuous live loop** (multi-agent, context overflow):

```bash
autopsy run examples/financial_research_pipeline.py
```

**Single-shot broken agent** (JSON decode / overflow):

```bash
autopsy run examples/broken_agent.py
```

Demo env knobs: `AUTOPSY_LOOP_DELAY_S`, `AUTOPSY_DEMO_MODE`, `AUTOPSY_LATENCY_SCALE`.

## Tests & CI

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check autopsy tests
```

GitHub Actions runs pytest + ruff on Python 3.11 and 3.12.

## Robustness

- Instrumentation never raises into user code
- Diagnose always returns a result (heuristic fallback)
- Session dirs are atomic (tmp + rename); SQLite index is rebuildable
- Default sampling keeps disk usage low (`errors` only unless promoted)

## License

MIT
