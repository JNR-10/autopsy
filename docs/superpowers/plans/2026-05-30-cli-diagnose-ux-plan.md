# CLI-First Diagnose UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. TDD every task. **Every command needs unit + integration tests before the phase is done.**

**Goal:** Reshape the autopsy CLI into `ls / show / diagnose / tail / export / import` with Rich human output and `--json` for scripts, surfacing detector verdicts in `show` and `ls`.

**Architecture:** Shared helpers in `autopsy/cli/resolve.py` and `output.py`. All session reads go through `LegacyBundleReader`. Tests use Click's `CliRunner` plus real sessions created by `Writer` in integration fixtures.

**Spec:** `docs/superpowers/specs/2026-05-30-cli-diagnose-ux-design.md`

---

## Phases

1. **Foundation** — `resolve.py`, `conftest.py`, session fixtures from Writer  
2. **`ls`** — rename/alias `sessions`, detector column, `--json`  
3. **`show`** — human + JSON, detector verdicts section  
4. **`diagnose --json`** — stable JSON output  
5. **`tail`** — finalized + live poll  
6. **`export` / `import`** — tar round-trip; deprecate `deploy`  
7. **`clean`** — fix v1 directory deletion  
8. **Integration workflows + green sweep**

## Testing rule (non-negotiable)

Each phase MUST add:
- Unit tests in `tests/cli/`
- At least one test in `tests/integration/test_cli_workflows.py` for new/changed commands

Do not mark a phase complete without both.

---

## Phase 1 — Foundation

### Task 1.1: Session resolution helper

**Files:** `autopsy/cli/resolve.py`, `tests/cli/test_resolve.py`, `tests/cli/conftest.py`

Implement:
```python
def resolve_session_id(reader: LegacyBundleReader, token: str) -> str:
    """Exact match, else unique prefix. Raises click.ClickException on failure."""
```

`conftest.py`: fixtures `session_root`, `writer_session_ok`, `writer_session_detector_fail` using Writer + empty_response or tool_loop.

### Task 1.2: JSON helpers

**Files:** `autopsy/cli/output.py` (stub serializers)

Commit messages:
- `feat(cli): add session id resolution helper`
- `feat(cli): add JSON output helpers for CLI commands`

---

## Phase 2 — ls

### Task 2.1: `autopsy ls` + `sessions` alias + `--json`

**Files:** modify `autopsy/cli/main.py`, `tests/cli/test_ls.py`, integration test in `test_cli_workflows.py`

Commit: `feat(cli): add ls command with detector column and --json`

---

## Phase 3 — show

### Task 3.1: `autopsy show`

**Files:** `autopsy/cli/main.py`, `tests/cli/test_show.py`, integration test

Commit: `feat(cli): add show command with detector verdict section`

---

## Phase 4 — diagnose --json

Commit: `feat(cli): add --json output to diagnose command`

---

## Phase 5 — tail

**Files:** `autopsy/cli/tail.py`, tests

Commit: `feat(cli): add tail command for live and finalized sessions`

---

## Phase 6 — export/import

**Files:** `autopsy/cli/export_import.py`, tests

Commits:
- `feat(cli): add export command (tar.gz default)`
- `feat(cli): add import command with reindex`

---

## Phase 7 — clean

Commit: `fix(cli): clean --all removes v1 session directories`

---

## Phase 8 — green sweep

- Full suite green
- Update README CLI section
- Commit: `chore: green test suite after CLI-first UX`

---

## Execution

Subagent-driven, one phase per subagent, commit commands after each phase. **Do NOT git commit** inside subagents unless user asks.
