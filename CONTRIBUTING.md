# Contributing to autopsy

Thanks for helping make agent post-mortems easier. This guide is the fast path from clone to merged PR.

**Questions?** Open a [GitHub issue](https://github.com/JNR-10/autopsy/issues) or a discussion — describe the failure mode you are trying to catch.

---

## Quick start (5 minutes)

```bash
git clone https://github.com/JNR-10/autopsy.git && cd autopsy
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,server,diagnose,fast]"
cp .env.example .env   # optional; diagnose tests mock providers by default
make test
make lint
```

Or without Make:

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check autopsy tests examples
```

---

## What we merge

- **Tests required** for behavior changes (unit and/or integration; CLI commands need both).
- **Ruff clean** on `autopsy`, `tests`, and `examples`.
- **[CHANGELOG.md](CHANGELOG.md)** entry under `[Unreleased]` for user-facing changes.
- **Focused diffs** — one concern per PR when possible.
- **No secrets** in fixtures, examples, or test session dirs.

CI runs on Python 3.11 and 3.12 (see [.github/workflows/ci.yml](.github/workflows/ci.yml)).

---

## Where to put code

| Change | Location | Tests |
|--------|----------|-------|
| Detector | `autopsy/detectors/` | `tests/unit/test_detectors_extended.py` or new `test_detectors_*.py` |
| CLI command / flag | `autopsy/cli/` | `tests/cli/` + `tests/integration/` |
| Capture / writer / store | `autopsy/core/` | `tests/unit/`, `tests/integration/` |
| Diagnose provider | `autopsy/diagnostics/` | patch `resolve_diagnose_provider` in tests |
| Example agent | `examples/` | optional; prefer minimal repro |
| Docs | `README.md`, `CONTRIBUTING.md` | n/a |

Mirror the package path under `tests/`.

---

## Good first contributions

Look for issues labeled **`good first issue`**, or pick one of these:

1. **New detector** — see cookbook below (best on-ramp).
2. **Catalog / docs** — detector description, README table, `.env.example` comment.
3. **Example script** — minimal agent that triggers a specific silent failure.
4. **CLI polish** — `--json` output, error messages, tab completion (discuss in issue first).

---

## Cookbook: add a built-in detector

1. **Copy a template** — start from [`autopsy/detectors/tool_loop.py`](autopsy/detectors/tool_loop.py).

2. **Implement `evaluate()`** — return a `DetectorVerdictEvent` with `verdict="fail"` or `"warn"`, or `None` if clean:

```python
class MyDetector:
    name = "my_detector"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        ...
```

3. **Register** in [`autopsy/detectors/registry.py`](autopsy/detectors/registry.py) (`_builtin_instances()` and `factories` if threshold-aware).

4. **Document** in [`autopsy/detectors/catalog.py`](autopsy/detectors/catalog.py) and optionally [`autopsy/detectors/defaults.py`](autopsy/detectors/defaults.py).

5. **Test** with synthetic events (no live LLM):

```bash
.venv/bin/python -m pytest tests/unit/test_detectors_extended.py -q -k my_detector
```

6. **CHANGELOG** — one line under `### Added`.

### Third-party detector (no fork)

```python
from autopsy.detectors.registry import register

register(MyDetector())
```

Enable via `AUTOPSY_DETECTORS=my_detector,...` or `@lens.trace(detectors=["my_detector"])`.

---

## Cookbook: CLI change

1. Add command in [`autopsy/cli/main.py`](autopsy/cli/main.py) (Click group).
2. Put logic in a dedicated module under `autopsy/cli/` when non-trivial.
3. Add **`--json`** if the command prints structured data.
4. Tests: invoke via `cli_runner` in `tests/cli/`; end-to-end in `tests/integration/test_cli_workflows.py` when appropriate.

---

## Running tests

```bash
make test          # default suite (excludes slow)
make test-slow     # perf, crash recovery, session-end benchmarks
make lint          # ruff
make check         # lint + test (what CI runs locally)
```

Slow tests are marked `@pytest.mark.slow` and excluded by default (`pyproject.toml` `addopts`).

---

## Scope: welcome vs discuss first

**Welcome without prior design issue**

- Detectors, CLI, compat readers, perf, tests, docs, `examples/`

**Open an issue first**

- New on-disk formats, breaking manifest changes
- Remote store backends (S3, etc.)
- Dashboard / WebSocket features
- OpenTelemetry exporters

We are **CLI-first**; optional server/dashboard changes should not block core capture work.

---

## Pull request checklist

- [ ] Tests pass: `make check` (or `make test` + `make lint`)
- [ ] CHANGELOG updated if users will notice
- [ ] No `.env`, API keys, or private session data in the diff
- [ ] PR template filled in

---

## Architecture pointers

- **User guide + internals:** [README.md](README.md) (developer guide section)
- **Extension hooks:** detectors, `DiagnoseProvider`, `TraceStore`, exporters — table in README
- **Design docs:** `docs/superpowers/specs/` (historical; README is the live reference)

---

## Code style

- Match surrounding code: types, naming, minimal scope.
- Prefer self-explanatory code; comments only for non-obvious invariants.
- Use `from __future__ import annotations` in new modules.

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License (see repository license file).
