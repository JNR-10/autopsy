# Failure Detection Layer

**Status:** Approved  
**Date:** 2026-05-30  
**Author:** brainstormed with the project lead  
**Sub-project:** 2 of 5 (see Roadmap section)

## Purpose

Sub-project #1 made capture cheap and durable. Agents can still "succeed" — no exception, HTTP 200, plausible-looking output — while being wrong: empty responses, infinite tool loops, silent no-ops. Standard observability never sees these.

Sub-project #2 adds **semantic failure detection**: pluggable heuristics that run when a traced call finishes, emit structured `detector_verdict` events, and **promote** the session to kept (same path as exceptions) so traces appear under `sample="errors"`.

## Goal

Ship a detector framework plus three built-in detectors that work out of the box via config/env, with zero custom code required for common cases. Detection runs at **session end only**, stays off the hot path except for bounded in-memory event buffering, and never blocks or crashes the host.

## Non-goals (explicitly out of scope)

- CLI changes (`autopsy ls` showing detector summaries) — sub-project #3.
- Diagnose prompt changes — sub-project #4.
- Dashboard UI — sub-project #5.
- LLM-as-judge detectors — too slow and overlaps with diagnose; custom detectors may call LLMs later, but none ship built-in.
- Streaming / per-event detection — deferred; session-end only in v1.
- New event kinds beyond the reserved `detector_verdict`.
- Changing capture-layer storage layout or format version (still v1).

## Constraints and budget

- **Detector evaluation at session end: p99 ≤ 2 ms** for the three built-ins combined on a typical session (<100 events).
- **Hot path:** append event reference to a bounded in-session buffer only; no detector logic on enqueue.
- **Never crash the host.** Detector exceptions → logged, rate-limited, treated as `pass`.
- **Never block the host** waiting on I/O inside detectors.
- Built-ins are **pure heuristics** over the in-memory event list (no network).

## Relationship to capture layer

Sub-project #1 reserved:

- `EventKind.DETECTOR_VERDICT` / `DetectorVerdictEvent` (`detector_name`, `verdict: pass|fail|warn`, `score`, `reason`).
- Writer `kept` promotion on `EventKind.ERROR`.
- Spec note: detector fail is a second signal to flush, same mechanism as errors.

This sub-project implements that seam.

### Required capture-layer adjustment

Today's **errors-default fast path** (root success with no `Session`, no events) makes detection impossible. v1 **replaces** the pure passthrough wrapper with a **light session path**:

1. Root `@lens.trace` always creates a `Session` with **deferred writer** (existing `Session.begin` behavior for `SampleMode.ERRORS`).
2. `Session.record_event` always appends to a **bounded in-session capture buffer** (deque, cap by event count and/or bytes — default 256 events / 2 MB).
3. Events are enqueued to the writer **only** when the writer is already active (sample=all, head-rate keep, error, detector fail, or buffer cap spill).
4. On `Session.end(outcome="ok")`, run detectors **before** `writer.end_session`.
5. If any detector returns `verdict="fail"`: activate writer, enqueue buffered events + verdict event(s), writer promotes session to `kept`, finalize with `status="error"` and `error_type="detector:<name>"` (first fail wins for manifest; all verdicts still written to events).
6. If all pass (or only `warn`): under `sample="errors"`, discard buffer — **no disk artifact** (same as today).

Sync and async wrappers share this path. The perf fast-path wrappers are removed; deferred session + bounded buffer replaces them while keeping hot-path cost low (ContextVar + deque append).

## Design overview

```
+-------------+   record_event    +------------------+
| @lens.trace | ----------------> | Session buffer   |
| interceptor |   (bounded deque) | (for detectors)  |
+-------------+                   +--------+---------+
                                          |
                              session.end | (sync, host thread)
                                          v
                                 +----------------+
                                 | DetectorRunner |
                                 | (enabled set)  |
                                 +-------+--------+
                                         |
                         +---------------+---------------+
                         v               v               v
                  empty_response    tool_loop    missing_output
                         |               |               |
                         +---------------+---------------+
                                         |
                         fail? --> DetectorVerdictEvent(s)
                               --> writer.activate + enqueue buffer
                               --> writer.kept = True
                               --> finalize (status=error)
```

Detectors never touch disk or the writer queue until a fail (or pre-existing keep reason).

## Detector framework

### Protocol

```python
class Detector(Protocol):
    name: str  # stable id, e.g. "tool_loop"

    def evaluate(self, events: Sequence[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        """Return a verdict event, or None / pass verdict if clean."""
```

- Input: ordered list of events from the session capture buffer (may be partial if cap truncated — detectors must tolerate).
- Output: `DetectorVerdictEvent` with `verdict` in `pass|fail|warn`.
- Run on the **host thread** at session end, before returning from the decorated function.

### Registry

`autopsy/detectors/registry.py`:

- `register(detector: Detector) -> None` — for custom detectors.
- `get(name: str) -> Detector | None`
- `builtin_detectors() -> dict[str, Detector]` — shipped built-ins.
- `resolve_enabled(config) -> list[Detector]` — merges defaults, config, env.

Built-in names are stable public API.

### Runner

`autopsy/detectors/runner.py`:

```python
def run_detectors(
    *,
    events: Sequence[BaseEvent],
    outcome: str,
    session_id: str,
    trace_id: str,
    parent_id: str | None,
    detectors: Sequence[Detector],
) -> list[DetectorVerdictEvent]:
```

- Runs detectors in registration order; each isolated in try/except.
- On exception: log warning, skip detector (equivalent to pass).
- Returns all verdict events (including `pass` if detector emits them; built-ins return only on fail/warn).
- **Fail promotion rule:** any `verdict=="fail"` → session kept. Multiple fails → all verdict events written; manifest `error_type` uses first fail's `detector_name`.

### Configuration

Extend `LensConfig`:

```python
enabled_detectors: list[str] = field(default_factory=lambda: [
    "empty_response", "tool_loop", "missing_output",
])
promote_on_warn: bool = False  # if True, warn also keeps session
max_capture_buffer_events: int = 256
max_capture_buffer_bytes: int = 2_097_152  # 2 MB
tool_loop_threshold: int = 5  # same tool N times in a row
max_tool_calls: int = 50     # total tool_call_start count
```

Environment:

| Variable | Meaning |
|----------|---------|
| `AUTOPSY_DETECTORS` | Comma-separated detector names, or `off` / empty for none |
| `AUTOPSY_PROMOTE_ON_WARN` | `0/1` |
| `AUTOPSY_TOOL_LOOP_THRESHOLD` | int, default 5 |
| `AUTOPSY_MAX_TOOL_CALLS` | int, default 50 |

Per-call override (optional v1):

```python
@lens.trace(detectors=["tool_loop"])      # only these
@lens.trace(detectors=[])                 # disable for this call
```

If `detectors=` is omitted, use config/env defaults.

## Built-in detectors (v1)

### `empty_response`

**Fail when:** the last `llm_response` event in the buffer has empty/whitespace `content`, and there is no non-empty later agent output in buffer.

**Reason example:** `"LLM returned empty content"`.

**Score:** `1.0` on fail.

Skips if no `llm_response` events (not an LLM agent).

### `tool_loop`

**Fail when either:**

- The same `tool_name` appears on **consecutive** `tool_call_start` events ≥ `tool_loop_threshold` (default 5), or
- Total `tool_call_start` count ≥ `max_tool_calls` (default 50).

**Reason example:** `"tool 'search' started 5 times consecutively"`.

### `missing_output`

**Fail when:** `outcome=="ok"`, session has at least one `llm_request` or `tool_call_start`, but no `llm_response` with non-empty content and no `agent_end` with non-empty `output_preview`.

**Reason example:** `"session completed without agent output"`.

Catches agents that ran tools/LLM but produced nothing meaningful.

### Warn vs fail

Built-ins only emit **`fail`** today. **`warn`** is reserved for future soft signals. `promote_on_warn=False` by default.

## Writer integration

In `Writer._process_batch`, add promotion:

```python
if ev.kind is EventKind.ERROR:
    state.kept = True
if ev.kind is EventKind.DETECTOR_VERDICT and ev.verdict == "fail":
    state.kept = True
if ev.kind is EventKind.DETECTOR_VERDICT and ev.verdict == "warn" and config.promote_on_warn:
    state.kept = True
```

In `_finalize_session_locked`, if outcome is `"ok"` but any buffered verdict was fail, treat as error for manifest (Session passes `outcome="error"` and `error_type` after detector run).

## Session integration

`Session.end()` flow:

```python
def end(self, *, outcome: str, error_type: str | None = None) -> None:
    verdicts = run_detectors(...)  # if detectors enabled
    if any(v.verdict == "fail" for v in verdicts):
        outcome = "error"
        error_type = error_type or f"detector:{first_fail.detector_name}"
    if verdicts or outcome == "error" or self.writer is not None or self._must_keep():
        w = self._activate_writer()
        for ev in self._capture_buffer:
            w.enqueue(ev)
        for v in verdicts:
            w.enqueue(v)
    self._capture_buffer.clear()
    if self.writer is not None:
        self.writer.end_session(self.session_id, outcome=outcome, error_type=error_type)
```

Helper `_must_keep()` covers sample=all, head_keep, already-promoted writer state.

## LegacyBundleReader

Add compat mapping in `read_v1_bundle` / `_v1_event_to_legacy`:

- `detector_verdict` + `verdict=="fail"` → legacy `event_type="node_error"` with `error_type="detector:<detector_name>"`, `error_message=<reason>`.
- `verdict=="warn"` → legacy `event_type="node_start"` with extra fields or skip (dashboard ignores warns in v1).
- `verdict=="pass"` → omit from legacy events (noise).

Minimum change so existing diagnostics/replay see detector failures as errors.

## Module layout

```
autopsy/
  detectors/
    __init__.py          # export register, run, built-in names
    registry.py
    runner.py
    empty_response.py
    tool_loop.py
    missing_output.py
  core/
    config.py            # new fields + env
    session.py           # capture buffer + end() hook
    decorator.py         # remove pure fast path; always light session
    writer.py              # promote on detector_verdict fail
    compat.py              # legacy mapping
tests/
  unit/
    test_detectors_*.py
    test_session_detectors.py
    test_writer_detector_promotion.py
  integration/
    test_detector_end_to_end.py
```

## Public API

```python
from autopsy.detectors import register, empty_response, tool_loop, missing_output

register(my_custom_detector)

# LensConfig(enabled_detectors=["tool_loop", "empty_response"])
# AUTOPSY_DETECTORS=off
```

No new top-level `autopsy` exports required in v1 beyond optional `autopsy.detectors` submodule.

## Testing strategy

| Test | Asserts |
|------|---------|
| Unit per built-in | Synthetic event lists → expected fail/pass |
| `test_runner_isolates_exceptions` | Broken detector does not break session |
| `test_session_end_fail_promotes` | Successful agent with empty LLM → session dir on disk under errors sample |
| `test_session_end_pass_discards` | Clean agent → no disk under errors sample |
| `test_writer_promotes_on_verdict` | Verdict fail event alone sets `kept` |
| Integration | Decorator + fake OpenAI → tool loop → manifest `status=error`, events contain verdict |
| Perf smoke | `run_detectors` on 100 events < 2 ms p99 |

Existing suite must stay green (146+ tests).

## Failure modes

| Failure | Handling |
|---------|----------|
| Detector raises | Log warning, skip, session continues |
| Capture buffer truncated | Detectors see tail only; may miss early loop — acceptable v1 tradeoff |
| Writer queue full on promote | Drop counter incremented; verdict still attempted |
| `AUTOPSY_DETECTORS=off` | No detector run; behavior matches pre-#2 capture layer |
| Nested trace calls | Detectors run only at **root** `Session.end()` (inner sessions don't exist — single root session) |

## Success criteria

- Three built-ins registered and enabled by default.
- Semantic failure (empty LLM response) under `sample="errors"` produces an on-disk session with `detector_verdict` + `status=error`.
- Clean successful agent under `sample="errors"` still produces **no** disk artifact.
- `LegacyBundleReader` exposes detector fails as legacy `node_error`.
- All existing tests pass; new detector tests green.
- Session-end detector suite p99 < 2 ms on 100-event fixture.

## Roadmap context

After this sub-project:

3. **CLI-first diagnose UX** — surface detector verdicts in `autopsy show`.
4. **Provider abstraction** — diagnose layer consumes traces with detector context.
5. **Demo/dashboard cleanup** — optional rich verdict UI.

Each sub-project gets its own spec (this document) and implementation plan.
