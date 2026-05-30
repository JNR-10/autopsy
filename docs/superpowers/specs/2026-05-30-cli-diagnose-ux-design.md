# CLI-First Diagnose UX

**Status:** Approved  
**Date:** 2026-05-30  
**Author:** brainstormed with the project lead  
**Sub-project:** 3 of 5 (see Roadmap section)

## Purpose

Sub-projects #1–#2 made capture and semantic failure detection trustworthy. Sub-project #3 makes **the CLI the daily-driver surface** for inspecting traces, understanding failures (including detector verdicts), and running diagnose/replay — without opening the dashboard.

## Goal

Reshape the Click CLI into a production-oriented command set: `ls`, `show`, `diagnose`, `tail`, `export`, `import` — Rich output for humans, `--json` for scripts. Every command path has **unit + integration tests** before merge.

## Non-goals (explicitly out of scope)

- Provider abstraction / `DiagnoseConfig` — sub-project #4.
- Dashboard UI changes — sub-project #5.
- Removing `autopsy run` / `autopsy serve` (demo commands stay).
- Rewriting diagnostics agents or prompts.
- Remote/cloud session backends.

## Constraints

- All commands read sessions via **`LegacyBundleReader`** (same as today).
- **Never crash** on bad input; exit code 1 + stderr message.
- **`--json` output** must be stable, machine-parseable, one JSON document per invocation (stdout).
- Human output uses **Rich** (already a dependency).
- Commands must work against **v1 session dirs** and **v0 JSON blobs** (via compat reader).

## Command surface

| Command | Purpose | `--json` |
|---------|---------|----------|
| `autopsy ls` | List sessions (new canonical name) | array of session summaries |
| `autopsy sessions` | **Alias** for `ls` (backward compat) | same |
| `autopsy show <id>` | Session detail: manifest summary, detector verdicts, error nodes | full bundle summary dict |
| `autopsy diagnose <id>` | Existing diagnose flow | `DiagnosisResult` dict |
| `autopsy tail <id>` | Stream new events for a **live** session; print last N for finalized | NDJSON events (optional `--json`) |
| `autopsy export [--out file]` | Export sessions to tarball or JSON | N/A (writes file) |
| `autopsy import <file>` | Import tarball/JSON into local store | N/A |
| `autopsy replay <id>` | Keep; add `--json` | replay result dict |
| `autopsy clean --all` | Fix for v1 dirs + index | N/A |
| `autopsy deploy` | **Deprecated alias** → `export` with warning | same as export |

### Session ID resolution (shared helper)

- Exact match on `session_id`.
- Else unique prefix match (existing diagnose behavior).
- Else exit 1 with clear error; prefix ambiguity lists candidates.

### `ls` columns (human)

`session_id`, `agent`, `status`, `errors`, `detector` (first fail name or `-`), `duration_ms`, `created`

### `show` sections (human)

1. Header: session_id, agent, status, error_type, duration  
2. **Detector verdicts** (if any): name, verdict, reason  
3. **Errors**: node_error / detector failures  
4. **Stats**: tokens, node count, dropped events (from manifest/bundle summary)  
5. Optional `--events` flag: compact event timeline (kind + preview)

### `tail` behavior (v1)

- **Finalized session:** print last `--lines N` (default 20) events and exit.
- **Live session** (`manifest.status == live`): poll `events.jsonl(.gz)` every 500ms, print new lines until Ctrl+C or session finalizes.
- `--json`: one JSON object per event line (NDJSON).

### `export` / `import`

- **export:** default `autopsy-export.tar.gz` containing `sessions/<id>/...` tree + `index.sqlite` if present. `--format json` keeps legacy single-file JSON for backward compat.
- **import:** unpack into configured session root; run `store.reindex()` after.

### `clean --all`

Delete v1 session **directories**, v0 `*.json` blobs, and rebuild/truncate index — not only `*.json` files (current bug).

## Module layout

```
autopsy/cli/
  main.py           # MODIFY — wire commands, aliases
  resolve.py        # NEW — session id resolution
  output.py         # NEW — Rich formatters + JSON serializers
  tail.py           # NEW — tail/poll logic
  export_import.py  # NEW — tar export/import
tests/cli/
  conftest.py       # CliRunner + tmp session fixtures
  test_ls.py
  test_show.py
  test_diagnose.py
  test_tail.py
  test_export_import.py
  test_clean.py
  test_resolve.py
tests/integration/
  test_cli_workflows.py   # writer → ls → show → diagnose (mocked LLM)
```

## Testing strategy (mandatory)

**Lesson from sub-project #2:** unit tests alone miss wiring bugs. Every command requires:

1. **Unit tests** (`CliRunner`, isolated tmp_path, real `LegacyBundleReader`).
2. **At least one integration test** per command in `test_cli_workflows.py` using a session written by `Writer` (not hand-built dicts).

| Command | Unit | Integration |
|---------|------|-------------|
| ls | list columns, empty state, `--json` schema | Writer session → `ls` sees it |
| show | detector verdicts rendered, `--json` | error session → show contains verdict |
| diagnose | not found, prefix match, `--json` | mock agent → JSON keys |
| tail | finalized last N lines | live session poll (short) |
| export/import | round-trip | tar out → import → ls sees session |
| clean | v1 dir deleted | create 2 sessions → clean → ls empty |
| resolve | prefix/ambiguous | used by show integration |

**CI gate:** `pytest tests/cli tests/integration/test_cli_workflows.py` must pass; full suite green.

## Success criteria

- `autopsy ls` shows detector fail column for semantic-failure sessions.
- `autopsy show <id>` displays detector verdicts and error_type `detector:*`.
- All commands support `--json` where specified.
- `clean --all` removes v1 session directories.
- export/import round-trip works across tmp dirs.
- **≥25 new CLI tests**, all green with full suite.
- No regressions in existing server/integration tests.

## Roadmap context

4. Provider abstraction + packaging  
5. Dashboard cleanup + production docs
