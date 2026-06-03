# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Cheap event byte estimates for capture/writer buffer caps (`event_bytes` module)
- `AUTOPSY_MAX_DETECTOR_EVAL_EVENTS` cap for session-end detector input
- v1 sessions: server builds `node_index` + `dag_edges` from captured events (dashboard latency/detail work on v1)
- `autopsy replay --live` and dashboard live-replay checkbox; manifest stores `agent_module_path` / checkpoints
- Demo routes moved to `examples/demo_routes.py` (loaded via `AUTOPSY_DEMO=1`, not shipped in core wheel)
- `AUTOPSY_PRODUCTION_ALERTING=1` preset (strict + warn persistence + full detector list)
- Detector ring (`max_detector_ring_events`) and `Writer.flush_now()` for full-trace evaluation
- Per-agent `@lens.trace(detector_profile=..., tool_loop_threshold=..., promote_on_warn=...)`
- Expanded legacy v0 field aliases (`tool_start`, `response_text`, `handled`, …)
- **12 default semantic detectors** (was 3): tool failures, truncation, orphan LLM/tools, unexecuted tool calls, swallowed errors, token-empty output, content filter, duplicate tool args
- Optional warn-tier detectors: `high_latency`, `error_storm`
- `autopsy detectors` / `autopsy detectors <id>` — catalog and offline re-run on v1 **and legacy v0** sessions
- `detectors/catalog.py` — names, descriptions, default set
- `detectors/profiles.py` — `strict` / `balanced` / `lenient` via `AUTOPSY_DETECTOR_PROFILE`
- `/health` returns `demo_enabled`
- `Session.events_for_detectors()` merges capture, writer buffer, and on-disk tail
- `ErrorEvent.attributes.handled` suppresses `unhandled_exception` false positives

### Changed

- Default `detector_full_trace` is off; production alerting no longer forces disk tail merge
- `events_for_detectors()` uses in-memory writer history unless full trace is enabled
- Agent module metadata resolved at session end (not on every trace entry)
- Sync/async decorator p99 perf tests moved to `pytest -m slow`
- `autopsy run` no longer enables demo routes by default; use `autopsy run --demo` or `examples/serve_with_demo.py`
- Removed `autopsy.demo` from published package; core server has no demo imports
- Dashboard replay messaging when demo routes are absent (404)
- **Warn-tier alerting:** `promote_on_warn` now finalizes and persists sessions on warn-only hits
- Default capture buffer for detectors: **1024 events / 8 MB** (was 256 / 2 MB)
- `orphan_tool_call` uses start/end pairing; `llm_tool_without_execution` respects turn boundaries
- CI `slow` job runs `pytest -m slow` (detector perf, crash recovery)

## [0.2.0] - 2026-05-30

### Added

- Production capture layer: v1 on-disk format, writer thread, bounded queue, crash-safe finalize
- Semantic failure detectors: `empty_response`, `tool_loop`, `missing_output`
- CLI-first commands: `ls`, `show`, `diagnose`, `tail`, `export`, `import`, `replay`, `clean`
- Pluggable diagnose providers: heuristic, OpenAI, Anthropic, GMI, Gemini, Ollama
- Unified `AutopsyConfig` via `load_config()` (capture + diagnose + server/demo settings)
- Optional dependency extras: `[server]`, `[diagnose]`, `[openai]`, `[anthropic]`, `[gemini]`, `[gmi]`
- Dashboard detector verdict panel and v1 session delete support
- GitHub Actions CI (Python 3.11/3.12) and PyPI publish workflow

### Changed

- Default sampling is `errors` — successful sessions are not persisted unless promoted
- `google-generativeai` replaced with `google-genai` for Gemini diagnosis
- FastAPI/uvicorn moved to optional `[server]` extra (core install is capture + CLI only)
- Demo fix-marker routes gated behind `AUTOPSY_DEMO=1` (`autopsy run` enables automatically)
- README and `.env.example` rewritten for production usage

### Removed

- Legacy in-process tracer; replaced by writer + `LegacyBundleReader` compat layer
- RocketRide deploy integration
- Hard dependencies on sponsor LLM SDKs

## [0.1.0] - 2025 (hackathon)

- Initial hackathon release: decorator, dashboard, GMI/Gemini diagnose, demo agents

[0.2.0]: https://github.com/JNR-10/autopsy/compare/v0.1.0...v0.2.0
