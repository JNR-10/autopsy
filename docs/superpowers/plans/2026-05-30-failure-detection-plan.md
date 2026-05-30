# Failure Detection Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pluggable failure-detection layer with three built-in heuristics (`empty_response`, `tool_loop`, `missing_output`) that evaluate at session end, emit `detector_verdict` events, and promote sessions to kept under `sample="errors"` — without changing the on-disk format version.

**Architecture:** Root `@lens.trace` calls always create a light `Session` with a bounded in-memory capture buffer. Events append to the buffer on every `record_event`; the writer stays deferred under errors sampling until an exception, detector fail, or other keep signal. At `Session.end()`, `DetectorRunner` scans the buffer; on `verdict="fail"`, buffered events + verdicts flush through the existing writer `kept` state machine (same path as `ERROR` events). `LegacyBundleReader` maps fail verdicts to legacy `node_error`.

**Tech Stack:** Python 3.11+, existing Pydantic v2 event models (`DetectorVerdictEvent` already defined), stdlib only in detectors. Tests: `pytest`, `pytest-asyncio`. Commands: `.venv/bin/python -m pytest`, `.venv/bin/ruff check autopsy tests`.

---

## Spec

Full design: `docs/superpowers/specs/2026-05-30-failure-detection-design.md`. If this plan disagrees with the spec, the spec wins.

## Phases

1. **Config** — `LensConfig` detector fields + env parsing.
2. **Detector framework** — Protocol, registry, runner.
3. **Built-ins** — `empty_response`, `tool_loop`, `missing_output`.
4. **Session buffer + end hook** — capture buffer, detector run, conditional flush.
5. **Writer promotion** — `DETECTOR_VERDICT` fail (and optional warn) sets `kept`.
6. **Decorator** — remove errors fast path; always light session; `detectors=` arg.
7. **Compat** — `LegacyBundleReader` maps fail verdicts to `node_error`.
8. **Integration + green sweep** — end-to-end test, perf smoke, full suite.

Each task is TDD: failing test → implement → green → commit. Every commit must leave the full suite green.

## Conventions

- Run tests: `.venv/bin/python -m pytest <path> -v`
- Lint: `.venv/bin/ruff check autopsy tests`
- Commit style: `feat(detectors): …`, `test(detectors): …`, `feat(session): …`
- User commits manually unless asked — still provide commit commands per task.

## File structure

```
autopsy/detectors/
  __init__.py
  registry.py
  runner.py
  empty_response.py
  tool_loop.py
  missing_output.py
autopsy/core/
  config.py          # MODIFY — detector fields + env
  session.py         # MODIFY — capture buffer + end() hook
  decorator.py       # MODIFY — remove fast path, detectors= arg
  writer.py          # MODIFY — promote on detector_verdict
  compat.py          # MODIFY — legacy mapping
tests/unit/
  test_config_detectors.py
  test_detector_registry.py
  test_detector_runner.py
  test_detector_empty_response.py
  test_detector_tool_loop.py
  test_detector_missing_output.py
  test_session_capture_buffer.py
  test_session_detectors.py
  test_writer_detector_promotion.py
  test_compat_detector_verdict.py
tests/integration/
  test_detector_end_to_end.py
tests/perf/
  test_detector_perf.py
```

---

## Phase 1 — Config

### Task 1.1: LensConfig detector fields + env loader

**Files:**
- Modify: `autopsy/core/config.py`
- Test: `tests/unit/test_config_detectors.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config_detectors.py`:

```python
"""Tests for detector-related LensConfig fields and env parsing."""
from __future__ import annotations

import pytest

from autopsy.core.config import LensConfig, load_config_from_env


def test_default_enabled_detectors():
    c = LensConfig()
    assert c.enabled_detectors == ["empty_response", "tool_loop", "missing_output"]


def test_env_autopsy_detectors_off(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DETECTORS", "off")
    c = load_config_from_env()
    assert c.enabled_detectors == []


def test_env_autopsy_detectors_subset(monkeypatch):
    monkeypatch.setenv("AUTOPSY_DETECTORS", "tool_loop,empty_response")
    c = load_config_from_env()
    assert c.enabled_detectors == ["tool_loop", "empty_response"]


def test_env_tool_loop_threshold(monkeypatch):
    monkeypatch.setenv("AUTOPSY_TOOL_LOOP_THRESHOLD", "3")
    c = load_config_from_env()
    assert c.tool_loop_threshold == 3


def test_env_promote_on_warn(monkeypatch):
    monkeypatch.setenv("AUTOPSY_PROMOTE_ON_WARN", "1")
    c = load_config_from_env()
    assert c.promote_on_warn is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_config_detectors.py -v`
Expected: FAIL — `AttributeError: 'LensConfig' object has no attribute 'enabled_detectors'`

- [ ] **Step 3: Write minimal implementation**

Add to `LensConfig` in `autopsy/core/config.py`:

```python
enabled_detectors: list[str] = field(default_factory=lambda: [
    "empty_response", "tool_loop", "missing_output",
])
promote_on_warn: bool = False
max_capture_buffer_events: int = 256
max_capture_buffer_bytes: int = 2_097_152
tool_loop_threshold: int = 5
max_tool_calls: int = 50
```

Extend `load_config_from_env`:

```python
if "AUTOPSY_DETECTORS" in os.environ:
    raw = os.environ["AUTOPSY_DETECTORS"].strip()
    if raw.lower() in ("", "off", "none"):
        c.enabled_detectors = []
    else:
        c.enabled_detectors = [x.strip() for x in raw.split(",") if x.strip()]
if "AUTOPSY_PROMOTE_ON_WARN" in os.environ:
    c.promote_on_warn = _parse_bool(os.environ["AUTOPSY_PROMOTE_ON_WARN"], c.promote_on_warn)
for env_key, attr in (
    ("AUTOPSY_TOOL_LOOP_THRESHOLD", "tool_loop_threshold"),
    ("AUTOPSY_MAX_TOOL_CALLS", "max_tool_calls"),
    ("AUTOPSY_MAX_CAPTURE_BUFFER_EVENTS", "max_capture_buffer_events"),
    ("AUTOPSY_MAX_CAPTURE_BUFFER_BYTES", "max_capture_buffer_bytes"),
):
    if env_key in os.environ:
        try:
            setattr(c, attr, int(os.environ[env_key]))
        except ValueError:
            logger.warning("autopsy: invalid %s=%r", env_key, os.environ[env_key])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_config_detectors.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint and commit**

```bash
git add autopsy/core/config.py tests/unit/test_config_detectors.py
git commit -m "feat(config): add detector settings and AUTOPSY_DETECTORS env"
```

---

## Phase 2 — Detector framework

### Task 2.1: Detector registry

**Files:**
- Create: `autopsy/detectors/__init__.py` (stub)
- Create: `autopsy/detectors/registry.py`
- Test: `tests/unit/test_detector_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_detector_registry.py`:

```python
"""Tests for the detector registry."""
from __future__ import annotations

from autopsy.core.config import LensConfig
from autopsy.detectors.registry import (
    builtin_detectors,
    get,
    register,
    resolve_enabled,
)


class _FakeDetector:
    name = "fake"

    def evaluate(self, events, *, outcome: str):
        return None


def test_builtin_detectors_has_three():
    b = builtin_detectors()
    assert set(b) == {"empty_response", "tool_loop", "missing_output"}


def test_register_and_get():
    d = _FakeDetector()
    register(d)
    assert get("fake") is d


def test_resolve_enabled_uses_config():
    cfg = LensConfig(enabled_detectors=["tool_loop"])
    names = [d.name for d in resolve_enabled(cfg)]
    assert names == ["tool_loop"]


def test_resolve_enabled_empty_when_off():
    cfg = LensConfig(enabled_detectors=[])
    assert resolve_enabled(cfg) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_detector_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.detectors'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/detectors/__init__.py`:

```python
"""Failure detectors — pluggable semantic failure heuristics."""
from __future__ import annotations

from .registry import builtin_detectors, get, register, resolve_enabled
from .runner import run_detectors

__all__ = [
    "register", "get", "builtin_detectors", "resolve_enabled", "run_detectors",
]
```

Create `autopsy/detectors/registry.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from autopsy.core.config import LensConfig
from autopsy.core.events import BaseEvent, DetectorVerdictEvent

_custom: dict[str, "Detector"] = {}


@runtime_checkable
class Detector(Protocol):
    name: str

    def evaluate(
        self, events: list[BaseEvent], *, outcome: str,
    ) -> DetectorVerdictEvent | None: ...


def register(detector: Detector) -> None:
    _custom[detector.name] = detector


def get(name: str) -> Detector | None:
    if name in _custom:
        return _custom[name]
    return _builtin_instances().get(name)


def _builtin_instances() -> dict[str, Detector]:
    from .empty_response import EmptyResponseDetector
    from .tool_loop import ToolLoopDetector
    from .missing_output import MissingOutputDetector
    return {
        "empty_response": EmptyResponseDetector(),
        "tool_loop": ToolLoopDetector(),
        "missing_output": MissingOutputDetector(),
    }


def builtin_detectors() -> dict[str, Detector]:
    return dict(_builtin_instances())


def resolve_enabled(config: LensConfig) -> list[Detector]:
    out: list[Detector] = []
    for name in config.enabled_detectors:
        d = get(name)
        if d is not None:
            out.append(d)
    return out
```

Create stub built-in modules (minimal pass-through until Phase 3):

`autopsy/detectors/empty_response.py`, `tool_loop.py`, `missing_output.py` each:

```python
from __future__ import annotations
from autopsy.core.events import BaseEvent, DetectorVerdictEvent

class EmptyResponseDetector:  # rename per file
    name = "empty_response"

    def evaluate(self, events: list[BaseEvent], *, outcome: str) -> DetectorVerdictEvent | None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_detector_registry.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint and commit**

```bash
git add autopsy/detectors/ tests/unit/test_detector_registry.py
git commit -m "feat(detectors): add Detector protocol and registry"
```

### Task 2.2: Detector runner

**Files:**
- Create: `autopsy/detectors/runner.py`
- Test: `tests/unit/test_detector_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_detector_runner.py`:

```python
"""Tests for DetectorRunner."""
from __future__ import annotations

from autopsy.core.events import (
    DetectorVerdictEvent, EventKind,
)
from autopsy.detectors.runner import run_detectors


class _FailDetector:
    name = "fail"

    def evaluate(self, events, *, outcome: str):
        return DetectorVerdictEvent(
            event_id="01HXY000000000000000000001",
            parent_id=None, session_id="s", trace_id="s",
            timestamp_ns=1, kind=EventKind.DETECTOR_VERDICT,
            detector_name="fail", verdict="fail", reason="bad",
        )


class _BrokenDetector:
    name = "broken"

    def evaluate(self, events, *, outcome: str):
        raise RuntimeError("boom")


def test_runner_returns_verdicts():
    out = run_detectors(
        events=[], outcome="ok", session_id="s", trace_id="s",
        parent_id=None, detectors=[_FailDetector()],
    )
    assert len(out) == 1
    assert out[0].verdict == "fail"


def test_runner_isolates_exceptions():
    out = run_detectors(
        events=[], outcome="ok", session_id="s", trace_id="s",
        parent_id=None, detectors=[_BrokenDetector(), _FailDetector()],
    )
    assert len(out) == 1
    assert out[0].detector_name == "fail"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_detector_runner.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_detectors'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/detectors/runner.py`:

```python
from __future__ import annotations

import logging
import time

from autopsy.core.events import DetectorVerdictEvent, EventKind
from autopsy.core.ulid import new_ulid
from autopsy.detectors.registry import Detector

logger = logging.getLogger("autopsy.detectors")


def run_detectors(
    *,
    events: list,
    outcome: str,
    session_id: str,
    trace_id: str,
    parent_id: str | None,
    detectors: list[Detector],
) -> list[DetectorVerdictEvent]:
    verdicts: list[DetectorVerdictEvent] = []
    for det in detectors:
        try:
            v = det.evaluate(events, outcome=outcome)
        except Exception:
            logger.warning("autopsy: detector %s raised", getattr(det, "name", det), exc_info=True)
            continue
        if v is None:
            continue
        if v.session_id != session_id:
            v = v.model_copy(update={"session_id": session_id, "trace_id": trace_id})
        if v.event_id in ("", None):
            v = v.model_copy(update={"event_id": new_ulid()})
        if v.timestamp_ns == 0:
            v = v.model_copy(update={"timestamp_ns": time.time_ns()})
        verdicts.append(v)
    return verdicts
```

Update `autopsy/detectors/__init__.py` to export `run_detectors` (already in plan above).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_detector_runner.py -v`
Expected: 2 passed

- [ ] **Step 5: Lint and commit**

```bash
git add autopsy/detectors/runner.py tests/unit/test_detector_runner.py
git commit -m "feat(detectors): add run_detectors with per-detector error isolation"
```

---

## Phase 3 — Built-in detectors

### Task 3.1: empty_response detector

**Files:**
- Modify: `autopsy/detectors/empty_response.py`
- Test: `tests/unit/test_detector_empty_response.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_detector_empty_response.py`:

```python
from autopsy.core.events import EventKind, LLMResponseEvent
from autopsy.detectors.empty_response import EmptyResponseDetector

SID = "01HXY000000000000000000001"


def _llm(content: str) -> LLMResponseEvent:
    return LLMResponseEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None, session_id=SID, trace_id=SID,
        timestamp_ns=1, kind=EventKind.LLM_RESPONSE,
        model="m", content=content,
    )


def test_fails_on_empty_last_response():
    d = EmptyResponseDetector()
    v = d.evaluate([_llm("   ")], outcome="ok")
    assert v is not None
    assert v.verdict == "fail"
    assert "empty" in v.reason.lower()


def test_passes_on_nonempty_response():
    d = EmptyResponseDetector()
    assert d.evaluate([_llm("hello")], outcome="ok") is None


def test_skips_when_no_llm_response():
    d = EmptyResponseDetector()
    assert d.evaluate([], outcome="ok") is None
```

- [ ] **Step 2–5:** Implement `EmptyResponseDetector.evaluate`: find last `LLM_RESPONSE`; if content strip empty → fail verdict. Run tests, lint, commit:

```bash
git add autopsy/detectors/empty_response.py tests/unit/test_detector_empty_response.py
git commit -m "feat(detectors): add empty_response built-in"
```

### Task 3.2: tool_loop detector

**Files:**
- Modify: `autopsy/detectors/tool_loop.py`
- Test: `tests/unit/test_detector_tool_loop.py`

- [ ] **Step 1: Write the failing test**

```python
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, ToolCallStartEvent
from autopsy.detectors.tool_loop import ToolLoopDetector

SID = "01HXY000000000000000000001"


def _tool(name: str, seq: str) -> ToolCallStartEvent:
    return ToolCallStartEvent(
        event_id=f"01HXY0000000000000000000{seq}",
        parent_id=None, session_id=SID, trace_id=SID,
        timestamp_ns=int(seq), kind=EventKind.TOOL_CALL_START,
        tool_name=name, tool_args={},
    )


def test_fails_on_consecutive_same_tool():
    cfg = LensConfig(tool_loop_threshold=3)
    d = ToolLoopDetector(config=cfg)
    events = [_tool("search", str(i)) for i in range(3)]
    v = d.evaluate(events, outcome="ok")
    assert v is not None and v.verdict == "fail"


def test_passes_on_alternating_tools():
    cfg = LensConfig(tool_loop_threshold=3)
    d = ToolLoopDetector(config=cfg)
    events = [_tool("a", "1"), _tool("b", "2"), _tool("a", "3")]
    assert d.evaluate(events, outcome="ok") is None
```

- [ ] **Implement** with `ToolLoopDetector(config: LensConfig | None = None)`, check consecutive same `tool_name` ≥ threshold OR total count ≥ `max_tool_calls`. Commit:

```bash
git commit -m "feat(detectors): add tool_loop built-in"
```

### Task 3.3: missing_output detector

**Files:**
- Modify: `autopsy/detectors/missing_output.py`
- Test: `tests/unit/test_detector_missing_output.py`

- [ ] **Step 1: Write the failing test**

```python
from autopsy.core.events import (
    AgentEndEvent, EventKind, LLMRequestEvent, LLMResponseEvent,
)
from autopsy.detectors.missing_output import MissingOutputDetector

SID = "01HXY000000000000000000001"


def test_fails_when_llm_ran_but_no_output():
    d = MissingOutputDetector()
    events = [
        LLMRequestEvent(
            event_id="01HXY000000000000000000001",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=1, kind=EventKind.LLM_REQUEST, model="m",
        ),
        LLMResponseEvent(
            event_id="01HXY000000000000000000002",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=2, kind=EventKind.LLM_RESPONSE,
            model="m", content="",
        ),
    ]
    v = d.evaluate(events, outcome="ok")
    assert v is not None and v.verdict == "fail"


def test_passes_when_agent_end_has_output():
    d = MissingOutputDetector()
    events = [
        AgentEndEvent(
            event_id="01HXY000000000000000000003",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=3, kind=EventKind.AGENT_END,
            duration_ms=1.0, output_preview="done",
        ),
    ]
    assert d.evaluate(events, outcome="ok") is None
```

- [ ] **Implement** per spec. Commit:

```bash
git commit -m "feat(detectors): add missing_output built-in"
```

---

## Phase 4 — Session capture buffer + detector hook

### Task 4.1: Bounded capture buffer on record_event

**Files:**
- Modify: `autopsy/core/session.py`
- Test: `tests/unit/test_session_capture_buffer.py`

- [ ] **Step 1: Write the failing test**

```python
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent
from autopsy.core.session import Session
from autopsy.core.writer import SampleMode

SID = "01HXY000000000000000000001"


def test_record_event_buffers_without_writer():
    cfg = LensConfig(default_sample="errors", max_capture_buffer_events=10)
    s = Session(
        session_id=SID, agent_name="a", sample=SampleMode.ERRORS,
        head_keep=False, writer=None, config=cfg,
        start_perf_ns=1, wall_ns=1,
    )
    ev = LogEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None, session_id=SID, trace_id=SID,
        timestamp_ns=1, kind=EventKind.LOG, name="x",
    )
    s.record_event(ev)
    assert len(s.capture_events()) == 1


def test_buffer_respects_max_events():
    cfg = LensConfig(default_sample="errors", max_capture_buffer_events=2)
    s = Session(
        session_id=SID, agent_name="a", sample=SampleMode.ERRORS,
        head_keep=False, writer=None, config=cfg,
        start_perf_ns=1, wall_ns=1,
    )
    for i in range(5):
        s.record_event(LogEvent(
            event_id=f"01HXY0000000000000000000{i:02d}",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=i, kind=EventKind.LOG, name=str(i),
        ))
    assert len(s.capture_events()) == 2
```

- [ ] **Step 2–5:** Add `_capture: deque[BaseEvent]`, `capture_events()` read-only accessor, append in `record_event` always (before writer logic), evict from left when over count/bytes cap. Commit:

```bash
git commit -m "feat(session): add bounded capture buffer for detectors"
```

### Task 4.2: Session.end runs detectors and flushes on fail

**Files:**
- Modify: `autopsy/core/session.py`
- Test: `tests/unit/test_session_detectors.py`

- [ ] **Step 1: Write the failing test**

```python
import time
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LLMResponseEvent
from autopsy.core.session import Session, get_writer
from autopsy.core.writer import SampleMode
import autopsy.core.session as session_mod

SID = "01HXY000000000000000000001"


def test_detector_fail_promotes_session_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    s = Session.begin(config=cfg, agent_name="a", sample="errors")
    s.record_event(LLMResponseEvent(
        event_id="01HXY00000000000000000000A",
        parent_id=None, session_id=s.session_id, trace_id=s.session_id,
        timestamp_ns=1, kind=EventKind.LLM_RESPONSE, model="m", content="  ",
    ))
    s.end(outcome="ok")
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    manifest = tmp_path / "sessions" / s.session_id / "manifest.json"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if manifest.exists():
            break
        time.sleep(0.02)
    assert manifest.exists()


def test_clean_session_no_disk_under_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    s = Session.begin(config=cfg, agent_name="a", sample="errors")
    s.end(outcome="ok")
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    assert not (tmp_path / "sessions").exists() or list((tmp_path / "sessions").iterdir()) == []
```

- [ ] **Step 3: Implement `Session.end`**

Key changes:
- Remove early return when `writer is None`.
- If `config.enabled_detectors`: `run_detectors(events=s.capture_events(), …, detectors=resolve_enabled(config))`.
- On any `verdict=="fail"`: set `outcome="error"`, `error_type=f"detector:{name}"`.
- If fail OR writer already active OR sample ALL/RATE head_keep: `_activate_writer()`, enqueue capture buffer events + verdicts, then `end_session`.
- Else: discard buffer (no writer call).

Pass `parent_id` from root agent node if available — use `None` for v1 (verdict events attach at session level).

- [ ] **Step 4–5:** Run `tests/unit/test_session_detectors.py` + full suite. Commit:

```bash
git commit -m "feat(session): run detectors at end and flush on fail"
```

---

## Phase 5 — Writer promotion

### Task 5.1: Writer promotes on detector_verdict fail

**Files:**
- Modify: `autopsy/core/writer.py`
- Test: `tests/unit/test_writer_detector_promotion.py`

- [ ] **Step 1: Write the failing test**

```python
import time
from autopsy.core.config import LensConfig
from autopsy.core.events import DetectorVerdictEvent, EventKind
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def test_verdict_fail_promotes_kept(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    w = Writer(config=cfg, store=__import__(
        "autopsy.core.store.local_fs", fromlist=["LocalFilesystemStore"]
    ).LocalFilesystemStore(root=tmp_path))
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        w.enqueue(DetectorVerdictEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=SID, trace_id=SID,
            timestamp_ns=1, kind=EventKind.DETECTOR_VERDICT,
            detector_name="tool_loop", verdict="fail", reason="loop",
        ))
        w.end_session(SID, outcome="error", error_type="detector:tool_loop")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / SID / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)
    assert (tmp_path / "sessions" / SID / "events.jsonl").exists() or (
        tmp_path / "sessions" / SID / "events.jsonl.gz"
    ).exists()
```

- [ ] **Step 3:** In `_process_batch`, after ERROR check:

```python
if ev.kind is EventKind.DETECTOR_VERDICT:
    if ev.verdict == "fail":
        state.kept = True
    elif ev.verdict == "warn" and self.config.promote_on_warn:
        state.kept = True
```

- [ ] **Commit:**

```bash
git commit -m "feat(writer): promote session kept on detector_verdict fail"
```

---

## Phase 6 — Decorator changes

### Task 6.1: Remove errors fast path; add detectors= arg

**Files:**
- Modify: `autopsy/core/decorator.py`
- Modify: `tests/perf/test_overhead.py` (may need threshold tweak after light session)
- Test: extend `tests/unit/test_decorator.py` or create `tests/unit/test_decorator_detectors.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_decorator_detectors.py`:

```python
import pytest
from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
import autopsy.core.session as session_mod


@pytest.mark.asyncio
async def test_root_async_creates_session_under_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def agent():
        from autopsy.core.context import current_session
        assert current_session() is not None
        return 1

    assert await agent() == 1


def test_per_call_detectors_override(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    lens = LensDecorator(config=cfg)

    @lens.trace(detectors=[])
    def agent():
        return 1

    assert agent() == 1
```

- [ ] **Step 3: Implement**

- Delete `errors_default_async_wrapper` and `errors_default_sync_wrapper` blocks entirely.
- Add `detectors=None` to `trace()` signature; thread through `_wrap` → `_invoke_sync` / `_invoke_async`.
- Store per-session detector list on `Session` (new field `_detectors: list[str] | None` set in `Session.begin(detectors=...)`).
- In `Session.end`, if session has `_detectors is not None`, temporarily override config enabled list.

- [ ] **Step 4:** Run full suite including `tests/perf/test_overhead.py`. If async/sync p99 regresses, acceptable — light session adds deque append; should stay <5ms. Tune if needed.

- [ ] **Commit:**

```bash
git commit -m "feat(decorator): always use light session path; add detectors= override"
```

---

## Phase 7 — Compat

### Task 7.1: LegacyBundleReader maps detector_verdict fail

**Files:**
- Modify: `autopsy/core/compat.py`
- Test: `tests/unit/test_compat_detector_verdict.py`

- [ ] **Step 1: Write the failing test**

```python
from autopsy.core.compat import _v1_event_to_legacy


def test_fail_verdict_maps_to_node_error():
    legacy = _v1_event_to_legacy({
        "kind": "detector_verdict",
        "event_id": "e1",
        "session_id": "s",
        "detector_name": "tool_loop",
        "verdict": "fail",
        "reason": "loop",
        "timestamp_ns": 1_000_000_000,
    })
    assert legacy["event_type"] == "node_error"
    assert legacy["error_type"] == "detector:tool_loop"
    assert legacy["error_message"] == "loop"


def test_pass_verdict_omitted():
    assert _v1_event_to_legacy({
        "kind": "detector_verdict", "verdict": "pass",
        "detector_name": "x", "timestamp_ns": 1,
    }) is None
```

- [ ] **Step 3:** Update `_v1_event_to_legacy` and filter `None` in `read_v1_bundle`. Commit:

```bash
git commit -m "feat(compat): map detector_verdict fail to legacy node_error"
```

---

## Phase 8 — Integration + green sweep

### Task 8.1: End-to-end detector test

**Files:**
- Create: `tests/integration/test_detector_end_to_end.py`

- [ ] **Step 1: Write integration test**

Simulate tool loop via direct event injection or fake OpenAI repeating tool calls; assert manifest `status=error`, events contain `detector_verdict`.

Pattern: reuse `test_capture_end_to_end.py` fixture style with `LensDecorator`, `InterceptorManager`, `default_sample="errors"`.

- [ ] **Commit:**

```bash
git commit -m "test(detectors): add end-to-end semantic failure capture test"
```

### Task 8.2: Detector perf smoke

**Files:**
- Create: `tests/perf/test_detector_perf.py`

```python
from tests.perf.harness import measure_overhead_ms
from autopsy.detectors.runner import run_detectors
from autopsy.detectors.registry import resolve_enabled
from autopsy.core.config import LensConfig
from autopsy.core.events import EventKind, LogEvent

def test_run_detectors_p99_under_2ms():
    cfg = LensConfig()
    events = [
        LogEvent(
            event_id=f"01HXY0000000000000000000{i:02d}",
            parent_id=None, session_id="s", trace_id="s",
            timestamp_ns=i, kind=EventKind.LOG, name=str(i),
        )
        for i in range(100)
    ]
    dets = resolve_enabled(cfg)

    def run():
        run_detectors(
            events=events, outcome="ok", session_id="s", trace_id="s",
            parent_id=None, detectors=dets,
        )

    out = measure_overhead_ms(baseline=lambda: None, traced=run, iterations=200, warmup=20)
    assert out["p99"] < 2.0, out
```

- [ ] **Commit:**

```bash
git commit -m "test(detectors): add session-end detector perf smoke test"
```

### Task 8.3: Full suite green sweep

- [ ] Run: `.venv/bin/python -m pytest tests/ -q`
- [ ] Run: `.venv/bin/ruff check autopsy tests`
- [ ] Fix any breakage (likely `Session.end` early-return tests, perf tests, replay tests).
- [ ] Update spec status to **Approved** in front matter.
- [ ] Commit:

```bash
git commit -m "chore: green test suite after failure-detection layer"
```

---

## Self-review (spec coverage)

| Spec section | Task(s) |
|---|---|
| Config fields + env | 1.1 |
| Detector Protocol + registry | 2.1 |
| Runner + error isolation | 2.2 |
| empty_response | 3.1 |
| tool_loop | 3.2 |
| missing_output | 3.3 |
| Capture buffer | 4.1 |
| Session.end hook + flush | 4.2 |
| Writer promotion | 5.1 |
| Remove fast path + detectors= | 6.1 |
| LegacyBundleReader | 7.1 |
| Integration test | 8.1 |
| Perf p99 ≤ 2ms | 8.2 |
| Full suite green | 8.3 |

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-30-failure-detection-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per phase (or task batch), review between phases.

**2. Inline Execution** — implement tasks in this session with checkpoints.

Which approach do you want?
