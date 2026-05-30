# autopsy

> _Your agent died. Here's why._
> One decorator. Full agent visibility. AI that diagnoses your AI.

`autopsy` wraps any async LLM agent with a single decorator, captures a full execution trace, streams it live to a local web dashboard, and runs an AI-powered diagnostic chain that identifies the root cause, suggests a code fix, and lets you replay the failing slice with the fix applied — all without leaving the dashboard.

Two AI products work together on every diagnosis:

- **GMI Cloud** (DeepSeek-V3.2 / Qwen3-Next-80B) runs the actual root-cause reasoning.
- **Google Gemini 2.5 Pro** is the long-context fallback if GMI rate-limits.

## Install

```bash
pip install -e .
```

## Quickstart

```python
from autopsy import lens

@lens.trace
async def my_agent(query: str):
    # your existing agent code - zero changes
    ...
```

```bash
autopsy run agent.py
# Dashboard opens at http://localhost:7823
```

## CLI

```bash
autopsy run examples/financial_research_pipeline.py   # run an agent + dashboard
autopsy serve                                          # start dashboard only
autopsy sessions                                       # list saved traces
autopsy diagnose <session_id>                          # AI root-cause analysis
autopsy replay <session_id>                            # simulated replay with fix
autopsy clean --all                                    # wipe local sessions
```

## What you get

- **Live DAG** of every agent hop, tool call, and LLM completion — pan, zoom, and live "LIVE" badge on the active run
- **AI diagnostics** — GMI Cloud reasoning with Gemini long-context fallback
- **Time-travel replay** — click any node and re-execute the failing slice with the fix; the live loop picks up the patched code on the next iteration
- **Latency breakdown** — see exactly where your agent is slow
- **OpenAI SDK auto-instrumented** — anything that uses OpenAI-compatible APIs (GMI, Together, Groq, ollama) is intercepted transparently
- **Zero-config dashboard** — polished vanilla-JS dashboard ships with the package; no Node.js required
- **Heuristic fallback** that still produces a useful diagnosis if every cloud LLM is unreachable

## Environment

Copy `.env.example` to `.env` and fill in your keys:

```bash
# Required for the AI-powered diagnostic (free tier works)
GMI_API_KEY=...                              # https://gmi.ai/console
GMI_DEFAULT_MODEL=deepseek-ai/DeepSeek-V3.2
GMI_FALLBACK_MODEL=Qwen/Qwen3-Next-80B-A3B-Instruct

# Optional: long-context fallback diagnoser
GOOGLE_AI_API_KEY=...                        # https://aistudio.google.com
GEMINI_MODEL=gemini-2.5-pro

AUTOPSY_PORT=7823
```

If everything is missing, autopsy falls back to a built-in heuristic diagnoser that still produces a sensible root-cause analysis — so the demo always works.

## Demo: continuous live loop (the main demo)

```bash
autopsy run examples/financial_research_pipeline.py
```

A continuously-running multi-agent pipeline:

> orchestrator → ticker-planner → 3 parallel researchers (each with 3 tools) → synthesizer → risk-checker → report-writer → publisher

Every ~8 seconds the pipeline runs another full iteration. The synthesizer is deliberately broken — it concatenates three 5KB researcher briefs into a single 15.6KB context and hits a 12KB limit. Real bug, real pattern.

The full live demo loop:

1. **Watch** the flowchart fill in live — agents turn green as they complete, then **two nodes go red** when the synthesizer hits context overflow. Use the **+ / − / ⊡** buttons (top-right of the graph), the mouse wheel, or click-and-drag to **pan and zoom** through the full DAG.
2. **Click** the red node → **🔍 Diagnose this node**. GMI Cloud's diagnosis renders with root cause, confidence score, and a code patch.
3. **Click "Apply fix & replay"**. The simulated replay goes green AND the live pipeline is signalled to switch to the fixed code path. The fix is ONLY applied when you click this button — diagnosing or running a replay without clicking does nothing to the live loop.
4. **Watch the next iteration** of the live loop run **fully green, end-to-end**, and keep looping forever. Your terminal prints `✅ FIX APPLIED — effective mode = success`.
5. **Reset** any time using the "↺ reset" button in the header to make it start failing again.
6. **Clear noise** with the small **`clear`** button in the TRACES sidebar (deletes finished traces, keeps the live one).

Knobs:

```bash
AUTOPSY_LOOP_DELAY_S=8        # seconds between iterations (default 8)
AUTOPSY_LATENCY_SCALE=2.5     # slow down sim latencies for live viewing (default 2.5)
AUTOPSY_DEMO_MODE=broken      # broken (default), success, timeout, bad_json
```

Run a single iteration (no looping) with `... --once`.

## Demo: the broken agent (alternate)

```bash
autopsy run examples/broken_agent.py
```

A deliberately broken 4-step pipeline (planner → search-tool → summarizer → response-assembler) that fails with a `JSONDecodeError` caused by `context_overflow`. Smaller, faster demo if you want to show the diagnose-and-fix cycle without the continuous loop.

## Architecture

```
autopsy/
  core/
    events.py                 # event dataclasses
    tracer.py                 # TraceSession — lifetime of one run
    decorator.py              # @lens.trace
    interceptor.py            # monkey-patches OpenAI SDK
    replay.py                 # ReplayEngine (simulated + live)
  diagnostics/
    gmi_agent.py              # GMI Cloud diagnostics (primary)
    gemini_agent.py           # long-context fallback
    prompts.py                # prompt templates + heuristics
  server/
    app.py                    # FastAPI + WebSocket + demo endpoints
    ws_manager.py             # broadcast manager
    _dashboard.html           # single-page dashboard (HTML/CSS)
    _dashboard_part{1,2,3}.js # session list, DAG renderer, detail panel
  cli/main.py                 # click-based CLI
  __init__.py                 # public: lens, LensConfig, TraceBundle, DiagnosisResult
examples/
  financial_research_pipeline.py  # main demo — continuous loop, multi-agent
  broken_agent.py                 # alternate demo — single-shot 4-step
  simple_agent.py                 # happy-path demo
tests/
  unit/, integration/         # pytest suite
```

## Tests & quality

```bash
.venv/bin/python -m pytest tests/ -q   # 22 passed
.venv/bin/ruff check autopsy tests     # All checks passed!
```

## Robustness notes

- The tracer never raises — a bug in instrumentation never crashes the user's agent
- Diagnostics has a strong heuristic fallback so the demo works even if every cloud LLM is down
- Session storage tries `~/.autopsy/sessions`, then `./.autopsy/sessions`, then `/tmp` — picks the first writable location
- WebSocket auto-reconnects with exponential backoff
- The OpenAI interceptor is install-once / refcounted so multiple concurrent sessions don't fight
- All session writes are atomic (write to `.tmp` then rename); index updates are file-locked

## License

MIT
