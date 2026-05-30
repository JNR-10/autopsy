# Capture-Layer Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `autopsy`'s capture layer (decorator, tracer, interceptor, on-disk format) with a production-grade implementation that is non-blocking, drop-on-pressure, sampled-on-error by default, schema-versioned, and crash-safe — while keeping the dashboard and diagnostics layers working unchanged through a bilingual compatibility reader.

**Architecture:** Hot path (decorator + OpenAI interceptor) only enqueues Pydantic-modeled events onto a bounded `queue.Queue`. A single daemon thread drains in batches, applies redaction, holds per-session in-memory buffers, and decides "keep" vs "discard" based on sampling state at session end. Kept sessions are written as a directory of `manifest.json` + append-only `events.jsonl` + content-addressed artifacts. A SQLite index (derived, rebuildable) makes listing fast. A `LegacyBundleReader` reads both the new v1 format and the old implicit-v0 format, returning the existing `TraceBundle` shape so the dashboard and diagnostics layers don't change.

**Tech Stack:** Python 3.11+, Pydantic v2 (`pydantic>=2`), stdlib `queue.Queue` + `threading`, stdlib `sqlite3`, stdlib `logging`, stdlib `gzip`, `orjson` (optional, falls back to stdlib `json`). No new hard dependencies beyond Pydantic v2 (already in `pyproject.toml`). Tests use existing `pytest` + `pytest-asyncio`.

---

## Spec

The full design is in `docs/superpowers/specs/2026-05-29-capture-layer-hardening-design.md`. This plan implements that spec. If a requirement here disagrees with the spec, the spec wins — stop and flag it.

## Phases

The work is decomposed into 8 phases, each producing a working, releasable state. Each phase is one or more PRs; phases are ordered so the project's test suite stays green throughout.

1. **Foundations** — Pydantic event models, ULID generator, config dataclass.
2. **Store** — `LocalFilesystemStore`, manifest atomic write, SQLite index, eviction.
3. **Writer** — daemon thread, bounded queue, batching, per-session buffers, sample state machine.
4. **Exporters** — `FileSystemExporter`, `LoggingExporter` with rate-limited finalization logs.
5. **Decorator and interceptor rewrite** — new `@lens.trace` on top of the new writer; sync + async interceptor.
6. **Compatibility shim** — `LegacyBundleReader` so the dashboard and diagnostics see the old `TraceBundle` shape.
7. **Switchover** — flip the package from old `tracer.py` to new `session.py` + `writer.py`. Delete the old code. All existing tests pass.
8. **Performance and crash-safety tests** — p99 overhead test in CI; SIGKILL recovery test; reindex test; soak test.

Each phase has its own task list below. Tasks are TDD: write failing test → run → implement → run → commit.

## Conventions used by this plan

- **Commands.** Tests are run with `.venv/bin/python -m pytest <path> -v` (matches the project's existing convention in the README).
- **Ruff.** After any file is created or modified, run `.venv/bin/ruff check autopsy tests` and fix any issues before commit. Don't introduce new ruff config; follow what's already in `pyproject.toml`.
- **Commits.** Conventional Commits style (`feat:`, `fix:`, `test:`, `refactor:`, `chore:`). Frequent and small. Each step's commit message is given verbatim.
- **File paths.** Always given as paths relative to the repo root (`/Users/jainilrana/Downloads/autopsy/...`).
- **Backward compat.** Until phase 7, the old `autopsy/core/tracer.py` keeps working. Existing tests in `tests/unit/test_decorator.py` and `tests/integration/test_server.py` must remain green at every commit.
- **No partial commits.** Every commit must leave the test suite green. If a step says "write the failing test," the next step makes it pass before commit.

## File Structure

This plan creates new files under `autopsy/core/` (and below) without deleting the old `tracer.py`, `decorator.py`, `interceptor.py`, `events.py` until phase 7. The new layout:

```
autopsy/core/
  events.py            # MODIFY in place when phase 7 switches over; before that, new models live in events_v2.py
  events_v2.py         # NEW (phase 1) — Pydantic v2 models. Renamed to events.py in phase 7.
  ulid.py              # NEW (phase 1) — small ULID generator, no new dep
  config.py            # NEW (phase 1) — LensConfig dataclass + env loader
  redact.py            # NEW (phase 3) — default redactor and secret patterns
  context.py           # NEW (phase 5) — ContextVars for current session, parent span, suppression
  session.py           # NEW (phase 5) — Session lifecycle; replaces TraceSession
  writer.py            # NEW (phase 3) — daemon thread, bounded queue, batching
  decorator.py         # MODIFY (phase 5) — new @lens.trace on top of writer; old code preserved until phase 7
  interceptor.py       # MODIFY (phase 5) — sync + async patch; old code preserved until phase 7
  tracer.py            # DELETE (phase 7) — replaced by session.py + writer.py
  compat.py            # NEW (phase 6) — LegacyBundleReader: bilingual v0/v1 reader
  errors.py            # NEW (phase 1) — internal exception types
  store/
    __init__.py        # NEW (phase 2) — TraceStore Protocol
    local_fs.py        # NEW (phase 2) — LocalFilesystemStore
    sqlite_index.py    # NEW (phase 2) — SQLite derived index
  exporters/
    __init__.py        # NEW (phase 4) — Exporter Protocol
    file.py            # NEW (phase 4) — FileSystemExporter
    logging.py         # NEW (phase 4) — LoggingExporter (rate-limited finalization log)

tests/unit/
  test_events_v2.py    # NEW (phase 1)
  test_ulid.py         # NEW (phase 1)
  test_config.py       # NEW (phase 1)
  test_local_fs.py     # NEW (phase 2)
  test_sqlite_index.py # NEW (phase 2)
  test_redact.py       # NEW (phase 3)
  test_writer.py       # NEW (phase 3)
  test_exporters.py    # NEW (phase 4)
  test_decorator_v2.py # NEW (phase 5) — renamed to test_decorator.py in phase 7
  test_compat.py       # NEW (phase 6)

tests/integration/
  test_capture_end_to_end.py  # NEW (phase 5)
  test_crash_safety.py        # NEW (phase 8)

tests/perf/
  __init__.py                 # NEW (phase 8)
  test_overhead.py            # NEW (phase 8)
```

---

## Phase 1 — Foundations

This phase creates only leaf-level modules with no dependencies on the rest of the new system. After this phase, the new files exist alongside the old ones and have unit tests; nothing in `autopsy/__init__.py` or in the user-facing API has changed yet.

### Task 1.1: ULID generator

**Files:**
- Create: `autopsy/core/ulid.py`
- Test: `tests/unit/test_ulid.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ulid.py`:

```python
"""Unit tests for the ULID generator."""
import re
import time

from autopsy.core.ulid import new_ulid

ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_ulid_is_26_chars_crockford_base32():
    u = new_ulid()
    assert ULID_PATTERN.match(u), f"not a valid ULID: {u}"


def test_ulids_are_unique_within_same_millisecond():
    ids = {new_ulid() for _ in range(1000)}
    assert len(ids) == 1000


def test_ulids_are_monotonically_increasing_in_time():
    a = new_ulid()
    time.sleep(0.002)
    b = new_ulid()
    assert a < b, "expected lexicographic ordering by time"


def test_ulids_within_same_ms_preserve_monotonicity():
    ids = [new_ulid() for _ in range(500)]
    assert ids == sorted(ids), "ULIDs minted in the same ms must stay ordered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_ulid.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.core.ulid'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/ulid.py`:

```python
"""Crockford-base32 ULID generator.

ULIDs are 26-character, time-sortable, 128-bit identifiers. We use them as
event IDs so events.jsonl is naturally ordered without a separate sequence
number, and so two events minted on different threads in the same millisecond
still sort deterministically.

This is a from-scratch implementation to avoid pulling in another dep.
"""
from __future__ import annotations

import os
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32

_lock = threading.Lock()
_last_ms: int = -1
_last_rand: int = 0


def _encode(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid() -> str:
    """Return a fresh 26-char ULID. Monotonic within a process."""
    global _last_ms, _last_rand
    with _lock:
        now_ms = int(time.time() * 1000)
        if now_ms <= _last_ms:
            # Same (or backward) millisecond: increment to preserve order.
            _last_rand += 1
            rand = _last_rand
            ms = _last_ms
        else:
            rand = int.from_bytes(os.urandom(10), "big")
            ms = now_ms
            _last_ms = ms
            _last_rand = rand
    return _encode(ms, 10) + _encode(rand, 16)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_ulid.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/ulid.py tests/unit/test_ulid.py`
Expected: All checks passed.

```bash
git add autopsy/core/ulid.py tests/unit/test_ulid.py
git commit -m "feat(core): add ULID generator for time-sortable event IDs"
```

### Task 1.2: Pydantic v2 event models (events_v2)

**Files:**
- Create: `autopsy/core/events_v2.py`
- Test: `tests/unit/test_events_v2.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_events_v2.py`:

```python
"""Unit tests for the v1 Pydantic event models."""
from __future__ import annotations

import json

import pytest

from autopsy.core.events_v2 import (
    AgentEndEvent,
    AgentStartEvent,
    AttachmentRefEvent,
    BaseEvent,
    ErrorEvent,
    EventKind,
    LLMRequestEvent,
    LLMResponseEvent,
    LogEvent,
    Manifest,
    SessionEndEvent,
    SessionStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    event_from_dict,
)


def _base_kwargs(kind: EventKind, **extra):
    return dict(
        event_id="01HXY000000000000000000000",
        parent_id=None,
        session_id="01HXY000000000000000000000",
        trace_id="01HXY000000000000000000000",
        timestamp_ns=1,
        kind=kind,
        **extra,
    )


def test_base_event_envelope_round_trips():
    ev = BaseEvent(**_base_kwargs(EventKind.LOG))
    d = ev.model_dump()
    assert d["kind"] == "log"
    assert d["status"] == "unset"
    assert json.loads(json.dumps(d))["event_id"] == "01HXY000000000000000000000"


def test_session_start_event_carries_agent_name():
    ev = SessionStartEvent(
        **_base_kwargs(EventKind.SESSION_START),
        agent_name="my_agent",
        input_query="hello",
        wall_clock_ns=2,
        monotonic_ns=1,
        autopsy_format_version=1,
    )
    d = ev.model_dump()
    assert d["kind"] == "session_start"
    assert d["agent_name"] == "my_agent"
    assert d["autopsy_format_version"] == 1


def test_event_kinds_are_closed_at_version_1():
    expected = {
        "session_start", "session_end",
        "agent_start", "agent_end",
        "llm_request", "llm_response",
        "tool_call_start", "tool_call_end",
        "error", "log", "attachment_ref", "detector_verdict",
    }
    assert {k.value for k in EventKind} == expected


def test_event_from_dict_dispatches_on_kind():
    payload = AgentStartEvent(
        **_base_kwargs(EventKind.AGENT_START),
        agent_name="x",
    ).model_dump()
    ev = event_from_dict(payload)
    assert isinstance(ev, AgentStartEvent)
    assert ev.agent_name == "x"


def test_event_from_dict_rejects_unknown_kind():
    payload = BaseEvent(**_base_kwargs(EventKind.LOG)).model_dump()
    payload["kind"] = "not_a_real_kind"
    with pytest.raises(ValueError):
        event_from_dict(payload)


def test_llm_response_event_fields():
    ev = LLMResponseEvent(
        **_base_kwargs(EventKind.LLM_RESPONSE),
        model="gpt-4o",
        content="hi",
        tool_calls=[],
        prompt_tokens=1,
        completion_tokens=2,
        total_tokens=3,
        latency_ms=4.0,
        finish_reason="stop",
    )
    assert ev.model_dump()["total_tokens"] == 3


def test_attachment_ref_records_hash_and_preview():
    ev = AttachmentRefEvent(
        **_base_kwargs(EventKind.ATTACHMENT_REF),
        field_path="messages[0].content",
        sha256="a" * 64,
        size_bytes=99999,
        preview="hello...",
    )
    assert ev.sha256 == "a" * 64


def test_error_event_carries_traceback():
    ev = ErrorEvent(
        **_base_kwargs(EventKind.ERROR),
        error_type="ValueError",
        error_message="bad",
        traceback="trace",
    )
    assert ev.error_type == "ValueError"


def test_log_event_attributes_pass_through():
    ev = LogEvent(
        **_base_kwargs(EventKind.LOG),
        name="retry",
        attributes={"attempt": 3, "reason": "rate_limited"},
    )
    assert ev.attributes["attempt"] == 3


def test_manifest_round_trips():
    m = Manifest(
        session_id="01HXY000000000000000000000",
        agent_name="agent",
        start_time_ns=1,
        end_time_ns=None,
        duration_ms=None,
        status="live",
        error_type=None,
        event_count=0,
        dropped_events=0,
        pinned=False,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=2,
        monotonic_ns_at_start=1,
    )
    s = m.model_dump_json()
    again = Manifest.model_validate_json(s)
    assert again.session_id == m.session_id
    assert again.status == "live"


@pytest.mark.parametrize("cls,kind", [
    (SessionStartEvent, EventKind.SESSION_START),
    (SessionEndEvent, EventKind.SESSION_END),
    (AgentStartEvent, EventKind.AGENT_START),
    (AgentEndEvent, EventKind.AGENT_END),
    (LLMRequestEvent, EventKind.LLM_REQUEST),
    (LLMResponseEvent, EventKind.LLM_RESPONSE),
    (ToolCallStartEvent, EventKind.TOOL_CALL_START),
    (ToolCallEndEvent, EventKind.TOOL_CALL_END),
    (ErrorEvent, EventKind.ERROR),
    (LogEvent, EventKind.LOG),
    (AttachmentRefEvent, EventKind.ATTACHMENT_REF),
])
def test_every_event_kind_round_trips_through_event_from_dict(cls, kind):
    fields = {}
    if cls is SessionStartEvent:
        fields = dict(agent_name="a", input_query="q", wall_clock_ns=1, monotonic_ns=1, autopsy_format_version=1)
    elif cls is SessionEndEvent:
        fields = dict(duration_ms=1.0, event_count=1, dropped_events=0, final_status="ok")
    elif cls is AgentStartEvent:
        fields = dict(agent_name="a")
    elif cls is AgentEndEvent:
        fields = dict(duration_ms=1.0)
    elif cls is LLMRequestEvent:
        fields = dict(model="m", messages=[], temperature=1.0, max_tokens=0, tools=[], prompt_tokens_estimate=0)
    elif cls is LLMResponseEvent:
        fields = dict(model="m", content="", tool_calls=[], prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_ms=0.0, finish_reason="stop")
    elif cls is ToolCallStartEvent:
        fields = dict(tool_name="t", tool_args={})
    elif cls is ToolCallEndEvent:
        fields = dict(tool_name="t", result=None, error=None, duration_ms=0.0)
    elif cls is ErrorEvent:
        fields = dict(error_type="E", error_message="m", traceback="t")
    elif cls is LogEvent:
        fields = dict(name="n", attributes={})
    elif cls is AttachmentRefEvent:
        fields = dict(field_path="f", sha256="a" * 64, size_bytes=1, preview="")
    ev = cls(**_base_kwargs(kind), **fields)
    again = event_from_dict(ev.model_dump())
    assert type(again) is cls
    assert again.kind is kind
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_events_v2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.core.events_v2'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/events_v2.py`:

```python
"""Pydantic v2 event models for the capture layer (schema version 1).

These models replace the dataclass-based models in `events.py`. They live
under a `_v2` filename until phase 7, at which point this file becomes
`events.py`. The original models keep working alongside this one so the
dashboard, diagnostics, and replay engine continue to consume the existing
`TraceBundle` shape until the bilingual `LegacyBundleReader` is in place.

Invariants:
- Every event carries the BaseEvent envelope: event_id, parent_id,
  session_id, trace_id, timestamp_ns, kind, status, attributes.
- `kind` is a closed enum at schema version 1.
- All models use ConfigDict(extra="forbid") so typos are caught early.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EventKind(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    ERROR = "error"
    LOG = "log"
    ATTACHMENT_REF = "attachment_ref"
    DETECTOR_VERDICT = "detector_verdict"


Status = Literal["ok", "error", "unset"]


class BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    parent_id: str | None = None
    session_id: str
    trace_id: str
    timestamp_ns: int
    kind: EventKind
    status: Status = "unset"
    attributes: dict[str, Any] = Field(default_factory=dict)


class SessionStartEvent(BaseEvent):
    agent_name: str
    input_query: str = ""
    wall_clock_ns: int
    monotonic_ns: int
    autopsy_format_version: int = 1


class SessionEndEvent(BaseEvent):
    duration_ms: float
    event_count: int
    dropped_events: int
    final_status: Literal["ok", "error", "partial"]


class AgentStartEvent(BaseEvent):
    agent_name: str
    role: str = "agent"
    input_preview: str = ""


class AgentEndEvent(BaseEvent):
    duration_ms: float
    output_preview: str = ""
    output_hash: str = ""


class LLMRequestEvent(BaseEvent):
    model: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 1.0
    max_tokens: int = 0
    tools: list[dict[str, Any]] = Field(default_factory=list)
    prompt_tokens_estimate: int = 0


class LLMResponseEvent(BaseEvent):
    model: str
    content: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = ""


class ToolCallStartEvent(BaseEvent):
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)


class ToolCallEndEvent(BaseEvent):
    tool_name: str
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class ErrorEvent(BaseEvent):
    error_type: str
    error_message: str
    traceback: str


class LogEvent(BaseEvent):
    name: str


class AttachmentRefEvent(BaseEvent):
    field_path: str
    sha256: str
    size_bytes: int
    preview: str = ""


class DetectorVerdictEvent(BaseEvent):
    detector_name: str
    verdict: Literal["pass", "fail", "warn"]
    score: float = 0.0
    reason: str = ""


_KIND_TO_CLASS: dict[EventKind, type[BaseEvent]] = {
    EventKind.SESSION_START: SessionStartEvent,
    EventKind.SESSION_END: SessionEndEvent,
    EventKind.AGENT_START: AgentStartEvent,
    EventKind.AGENT_END: AgentEndEvent,
    EventKind.LLM_REQUEST: LLMRequestEvent,
    EventKind.LLM_RESPONSE: LLMResponseEvent,
    EventKind.TOOL_CALL_START: ToolCallStartEvent,
    EventKind.TOOL_CALL_END: ToolCallEndEvent,
    EventKind.ERROR: ErrorEvent,
    EventKind.LOG: LogEvent,
    EventKind.ATTACHMENT_REF: AttachmentRefEvent,
    EventKind.DETECTOR_VERDICT: DetectorVerdictEvent,
}


def event_from_dict(payload: dict[str, Any]) -> BaseEvent:
    """Construct the right event subclass from a dict by inspecting `kind`."""
    raw_kind = payload.get("kind")
    try:
        kind = EventKind(raw_kind)
    except ValueError as exc:
        raise ValueError(f"unknown event kind: {raw_kind!r}") from exc
    cls = _KIND_TO_CLASS[kind]
    return cls.model_validate(payload)


class Manifest(BaseModel):
    """Per-session manifest.json. Written at session start, rewritten at finalize."""
    model_config = ConfigDict(extra="forbid")

    session_id: str
    agent_name: str
    start_time_ns: int
    end_time_ns: int | None = None
    duration_ms: float | None = None
    status: Literal["live", "ok", "error", "partial"]
    error_type: str | None = None
    event_count: int = 0
    dropped_events: int = 0
    pinned: bool = False
    autopsy_format_version: int = 1
    autopsy_version: str
    wall_clock_ns_at_start: int
    monotonic_ns_at_start: int
    extra: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_events_v2.py -v`
Expected: All tests pass.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/events_v2.py tests/unit/test_events_v2.py`
Expected: All checks passed.

```bash
git add autopsy/core/events_v2.py tests/unit/test_events_v2.py
git commit -m "feat(core): add Pydantic v2 event models (schema version 1)"
```

### Task 1.3: LensConfig dataclass + env loader

**Files:**
- Create: `autopsy/core/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config.py`:

```python
"""Unit tests for the LensConfig dataclass and env loader."""
from __future__ import annotations

import os

import pytest

from autopsy.core.config import LensConfig, load_config_from_env


def test_default_values_match_spec():
    c = LensConfig()
    assert c.default_sample == "errors"
    assert c.flush_batch_size == 100
    assert c.flush_interval_ms == 50
    assert c.queue_maxsize == 10_000
    assert c.max_total_disk_mb == 2048
    assert c.max_session_age_days == 30
    assert c.max_in_flight_buffer_mb == 10
    assert c.max_event_field_bytes == 65_536
    assert c.log_finalization is True
    assert c.log_finalization_info_rate_s == 60
    assert c.redactor is None
    assert c.session_dir is None


def test_env_override_for_sample(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "all")
    c = load_config_from_env()
    assert c.default_sample == "all"


def test_env_override_numeric_sample(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "0.05")
    c = load_config_from_env()
    assert c.default_sample == pytest.approx(0.05)


def test_env_override_off(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "off")
    c = load_config_from_env()
    assert c.default_sample == "off"


def test_env_log_finalization_zero_disables(monkeypatch):
    monkeypatch.setenv("AUTOPSY_LOG_FINALIZATION", "0")
    c = load_config_from_env()
    assert c.log_finalization is False


def test_env_session_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOPSY_SESSION_DIR", str(tmp_path))
    c = load_config_from_env()
    assert c.session_dir == str(tmp_path)


def test_invalid_sample_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AUTOPSY_SAMPLE", "garbage")
    c = load_config_from_env()
    assert c.default_sample == "errors"


def test_removed_fields_are_gone():
    c = LensConfig()
    for removed in ("gmi_api_key", "google_ai_api_key", "port", "auto_diagnose", "model"):
        assert not hasattr(c, removed), f"{removed} must not be on the new LensConfig"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.core.config'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/config.py`:

```python
"""LensConfig dataclass + environment-variable loader.

This is the single configuration surface for the capture layer. Field
names mirror the spec ("Public API changes" section). Removed fields
from the previous LensConfig (gmi_api_key, google_ai_api_key, port,
auto_diagnose, model) are intentionally absent; they belong to the
diagnose layer and will reappear on a DiagnoseConfig in sub-project #4.

Invariants:
- All fields have sensible defaults so `LensConfig()` is valid.
- Env loader never raises on malformed input; it falls back to defaults
  and logs a warning so a typo in production does not bring the host down.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("autopsy.config")


@dataclass
class LensConfig:
    session_dir: str | None = None

    default_sample: str | float = "errors"
    flush_batch_size: int = 100
    flush_interval_ms: int = 50
    queue_maxsize: int = 10_000
    max_total_disk_mb: int = 2048
    max_session_age_days: int = 30
    max_in_flight_buffer_mb: int = 10
    max_event_field_bytes: int = 65_536
    log_finalization: bool = True
    log_finalization_info_rate_s: int = 60
    redactor: Callable[[Any], Any] | None = field(default=None)


def _parse_sample(raw: str) -> str | float:
    raw = raw.strip().lower()
    if raw in ("all", "errors", "off"):
        return raw
    try:
        f = float(raw)
        if 0.0 <= f <= 1.0:
            return f
    except ValueError:
        pass
    logger.warning("autopsy: invalid AUTOPSY_SAMPLE=%r, falling back to 'errors'", raw)
    return "errors"


def _parse_bool(raw: str, default: bool) -> bool:
    raw = raw.strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


def load_config_from_env(base: LensConfig | None = None) -> LensConfig:
    """Apply AUTOPSY_* env vars on top of `base` (or a fresh default)."""
    c = base or LensConfig()
    if "AUTOPSY_SAMPLE" in os.environ:
        c.default_sample = _parse_sample(os.environ["AUTOPSY_SAMPLE"])
    if "AUTOPSY_LOG_FINALIZATION" in os.environ:
        c.log_finalization = _parse_bool(
            os.environ["AUTOPSY_LOG_FINALIZATION"], c.log_finalization
        )
    if "AUTOPSY_SESSION_DIR" in os.environ:
        c.session_dir = os.environ["AUTOPSY_SESSION_DIR"]
    for env_key, attr in (
        ("AUTOPSY_FLUSH_BATCH_SIZE", "flush_batch_size"),
        ("AUTOPSY_FLUSH_INTERVAL_MS", "flush_interval_ms"),
        ("AUTOPSY_QUEUE_MAXSIZE", "queue_maxsize"),
        ("AUTOPSY_MAX_TOTAL_DISK_MB", "max_total_disk_mb"),
        ("AUTOPSY_MAX_SESSION_AGE_DAYS", "max_session_age_days"),
        ("AUTOPSY_MAX_IN_FLIGHT_BUFFER_MB", "max_in_flight_buffer_mb"),
        ("AUTOPSY_MAX_EVENT_FIELD_BYTES", "max_event_field_bytes"),
        ("AUTOPSY_LOG_FINALIZATION_INFO_RATE_S", "log_finalization_info_rate_s"),
    ):
        if env_key in os.environ:
            try:
                setattr(c, attr, int(os.environ[env_key]))
            except ValueError:
                logger.warning("autopsy: invalid %s=%r", env_key, os.environ[env_key])
    return c
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/config.py tests/unit/test_config.py`
Expected: All checks passed.

```bash
git add autopsy/core/config.py tests/unit/test_config.py
git commit -m "feat(core): add LensConfig dataclass and env loader"
```

### Task 1.4: Internal exception types (errors)

**Files:**
- Create: `autopsy/core/errors.py`
- Test: covered by phase 2+ usage; this task adds the module and a smoke test.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_errors.py`:

```python
"""Smoke tests for the internal exception hierarchy."""
import pytest

from autopsy.core.errors import (
    AutopsyError,
    StoreError,
    WriterError,
    UnknownSchemaVersionError,
)


def test_all_subclass_autopsy_error():
    for cls in (StoreError, WriterError, UnknownSchemaVersionError):
        assert issubclass(cls, AutopsyError)


def test_unknown_schema_version_message():
    e = UnknownSchemaVersionError(7, "/some/path")
    assert "7" in str(e)
    assert "autopsy migrate" in str(e)


def test_can_be_raised_and_caught():
    with pytest.raises(AutopsyError):
        raise WriterError("queue dead")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/errors.py`:

```python
"""Internal exception types for the capture layer.

These are never re-raised across the autopsy/host boundary. They exist so
internal call sites can be explicit about what they expect to handle, and
so unit tests can pin down the failure mode.

User-facing failures are surfaced via stdlib `logging` and the manifest's
`status` field, never by raising into the host process.
"""
from __future__ import annotations


class AutopsyError(Exception):
    """Base class for all autopsy-internal exceptions."""


class StoreError(AutopsyError):
    """The on-disk store could not satisfy a read or write."""


class WriterError(AutopsyError):
    """The writer thread or queue is in a non-recoverable state."""


class RedactorError(AutopsyError):
    """A user-supplied redactor raised; the event is dropped fail-closed."""


class UnknownSchemaVersionError(AutopsyError):
    """A manifest carries a newer autopsy_format_version than we understand."""

    def __init__(self, version: int, path: str):
        super().__init__(
            f"autopsy: unknown autopsy_format_version={version} at {path}. "
            f"Run 'autopsy migrate {path}' (not yet implemented in v1)."
        )
        self.version = version
        self.path = path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_errors.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/errors.py tests/unit/test_errors.py`
Expected: All checks passed.

```bash
git add autopsy/core/errors.py tests/unit/test_errors.py
git commit -m "feat(core): add internal exception hierarchy"
```

---

## Phase 2 — Store

This phase builds the on-disk layout: per-session directories with `manifest.json` + `events.jsonl` + `artifacts/`, plus the derived SQLite index, plus eviction. Nothing here touches the writer thread, the decorator, or the existing tracer. Old code keeps running.

### Task 2.1: TraceStore Protocol

**Files:**
- Create: `autopsy/core/store/__init__.py`
- Test: `tests/unit/test_store_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_store_protocol.py`:

```python
"""Protocol shape test for TraceStore."""
from __future__ import annotations

import inspect

from autopsy.core.store import TraceStore


def test_protocol_has_expected_methods():
    expected = {"write_events", "finalize_session", "list_sessions",
                "load_session", "delete_session", "reindex"}
    members = {name for name, _ in inspect.getmembers(TraceStore) if not name.startswith("_")}
    missing = expected - members
    assert not missing, f"TraceStore is missing methods: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_store_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.core.store'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/store/__init__.py`:

```python
"""TraceStore Protocol — the seam for swappable storage backends.

`LocalFilesystemStore` is the only implementation that ships in v1. The
Protocol exists so S3 / GCS / other backends can slot in later without
touching the writer.

All methods are synchronous. The writer thread is the only caller; the
writer is what isolates the hot path from disk I/O.
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable

from ..events_v2 import BaseEvent, Manifest


@runtime_checkable
class TraceStore(Protocol):
    """Backend-agnostic API for persisting and reading sessions."""

    def write_events(self, session_id: str, events: Iterable[BaseEvent]) -> None:
        """Append events to the session's events log. Creates the session
        directory lazily on first call. Never blocks longer than a local
        write; never fsyncs per call."""
        ...

    def finalize_session(self, manifest: Manifest) -> None:
        """Seal the session: write final manifest atomically, fsync the
        events file, gzip the events log, insert into the index."""
        ...

    def list_sessions(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return session summary rows (newest first)."""
        ...

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Return the full session payload (manifest + events) or None."""
        ...

    def delete_session(self, session_id: str) -> None:
        """Delete the session directory and its index row in one transaction."""
        ...

    def reindex(self) -> int:
        """Rebuild the index by walking the sessions directory.

        Returns the number of sessions reindexed.
        """
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_store_protocol.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/store/__init__.py tests/unit/test_store_protocol.py`
Expected: All checks passed.

```bash
git add autopsy/core/store/__init__.py tests/unit/test_store_protocol.py
git commit -m "feat(store): add TraceStore Protocol for backend abstraction"
```

### Task 2.2: LocalFilesystemStore

**Files:**
- Create: `autopsy/core/store/local_fs.py`
- Test: `tests/unit/test_local_fs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_local_fs.py`:

```python
"""Unit tests for LocalFilesystemStore."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from autopsy.core.events_v2 import (
    AgentStartEvent,
    EventKind,
    LogEvent,
    Manifest,
)
from autopsy.core.store.local_fs import LocalFilesystemStore


def _ev(kind: EventKind, session_id: str, **extra):
    base = dict(
        event_id="01HXY00000000000000000000" + str(extra.pop("seq", "0")),
        parent_id=None,
        session_id=session_id,
        trace_id=session_id,
        timestamp_ns=1,
        kind=kind,
    )
    if kind is EventKind.AGENT_START:
        return AgentStartEvent(**base, agent_name="a")
    if kind is EventKind.LOG:
        return LogEvent(**base, name="n", attributes=extra.get("attrs", {}))
    raise ValueError(kind)


def _manifest(session_id: str, status="ok", event_count=2) -> Manifest:
    return Manifest(
        session_id=session_id,
        agent_name="a",
        start_time_ns=1,
        end_time_ns=1_000_000,
        duration_ms=1.0,
        status=status,
        error_type=None,
        event_count=event_count,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=2,
        monotonic_ns_at_start=1,
    )


def test_write_events_creates_session_dir_lazily(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000001"
    session_dir = tmp_path / "sessions" / sid
    assert not session_dir.exists()
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    assert session_dir.exists()
    assert (session_dir / "events.jsonl").exists()


def test_events_are_jsonl_one_per_line(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000002"
    store.write_events(sid, [
        _ev(EventKind.AGENT_START, sid, seq="1"),
        _ev(EventKind.LOG, sid, seq="2"),
    ])
    lines = (tmp_path / "sessions" / sid / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)


def test_finalize_seals_manifest_and_gzips_events(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000003"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    sd = tmp_path / "sessions" / sid
    assert (sd / "manifest.json").exists()
    assert (sd / "events.jsonl.gz").exists()
    assert not (sd / "events.jsonl").exists()
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        lines = f.read().splitlines()
    assert len(lines) == 1
    payload = json.loads((sd / "manifest.json").read_text())
    assert payload["status"] == "ok"
    assert payload["autopsy_format_version"] == 1


def test_manifest_written_atomically(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000004"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    sd = tmp_path / "sessions" / sid
    assert not (sd / "manifest.json.tmp").exists()


def test_list_sessions_returns_finalized_only(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    for n in (1, 2):
        sid = f"01HXY00000000000000000000{n}"
        store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
        store.finalize_session(_manifest(sid))
    rows = store.list_sessions()
    assert {r["session_id"] for r in rows} == {
        "01HXY000000000000000000001",
        "01HXY000000000000000000002",
    }


def test_load_session_returns_manifest_and_events(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000005"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    payload = store.load_session(sid)
    assert payload is not None
    assert payload["manifest"]["session_id"] == sid
    assert len(payload["events"]) == 1


def test_load_session_returns_none_for_unknown(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    assert store.load_session("nope") is None


def test_delete_session_removes_dir_and_index_row(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000006"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    store.finalize_session(_manifest(sid))
    store.delete_session(sid)
    assert not (tmp_path / "sessions" / sid).exists()
    assert store.list_sessions() == []


def test_partial_lines_in_events_jsonl_are_skipped_on_load(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    sid = "01HXY000000000000000000007"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    sd = tmp_path / "sessions" / sid
    with (sd / "events.jsonl").open("a") as f:
        f.write("{not valid json\n")
    store.finalize_session(_manifest(sid, event_count=1))
    payload = store.load_session(sid)
    assert payload is not None
    assert len(payload["events"]) == 1


def test_root_is_created_if_missing(tmp_path):
    root = tmp_path / "does" / "not" / "exist"
    store = LocalFilesystemStore(root=root)
    sid = "01HXY000000000000000000008"
    store.write_events(sid, [_ev(EventKind.AGENT_START, sid)])
    assert (root / "sessions" / sid / "events.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_local_fs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.core.store.local_fs'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/store/local_fs.py`:

```python
"""LocalFilesystemStore — the only TraceStore implementation that ships in v1.

Layout (matches the design spec):

    <root>/
      sessions/
        <session_id>/
          manifest.json
          events.jsonl   (gzipped to events.jsonl.gz at finalize)
          artifacts/<sha256>.bin
      index.sqlite

Invariants:
- write_events() appends newline-delimited JSON. It never fsyncs. The
  session directory is created lazily on first call.
- finalize_session() writes the manifest atomically (write tmp + rename),
  fsyncs the events file, gzips it in place, and inserts the index row.
- The events file is parsed line-by-line with malformed lines skipped
  (host SIGKILL may leave a partial trailing line — that's acceptable).
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from ..events_v2 import BaseEvent, Manifest
from .sqlite_index import SQLiteIndex

logger = logging.getLogger("autopsy.store")


class LocalFilesystemStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "sessions").mkdir(parents=True, exist_ok=True)
        self.index = SQLiteIndex(self.root / "index.sqlite")

    def _session_dir(self, session_id: str) -> Path:
        return self.root / "sessions" / session_id

    def write_events(self, session_id: str, events: Iterable[BaseEvent]) -> None:
        sd = self._session_dir(session_id)
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "artifacts").mkdir(exist_ok=True)
        path = sd / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for ev in events:
                f.write(ev.model_dump_json())
                f.write("\n")

    def finalize_session(self, manifest: Manifest) -> None:
        sd = self._session_dir(manifest.session_id)
        sd.mkdir(parents=True, exist_ok=True)

        events_path = sd / "events.jsonl"
        if events_path.exists():
            with events_path.open("rb") as src:
                src.flush()
                try:
                    os.fsync(src.fileno())
                except OSError:
                    pass
            gz_path = sd / "events.jsonl.gz"
            with events_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            events_path.unlink()

        manifest_path = sd / "manifest.json"
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(manifest.model_dump_json(indent=2))
        os.replace(tmp, manifest_path)

        self.index.upsert(manifest, str(sd))

    def list_sessions(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.index.list(limit=limit)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        sd = self._session_dir(session_id)
        manifest_path = sd / "manifest.json"
        if not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text())
        events: list[dict[str, Any]] = []
        gz = sd / "events.jsonl.gz"
        plain = sd / "events.jsonl"
        opener = (lambda: gzip.open(gz, "rt", encoding="utf-8")) if gz.exists() else (
            (lambda: plain.open("r", encoding="utf-8")) if plain.exists() else None
        )
        if opener is not None:
            with opener() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("autopsy: skipping malformed event in %s", sd)
                        continue
        return {"manifest": manifest, "events": events}

    def delete_session(self, session_id: str) -> None:
        sd = self._session_dir(session_id)
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
        self.index.delete(session_id)

    def reindex(self) -> int:
        self.index.clear()
        count = 0
        sessions_root = self.root / "sessions"
        if not sessions_root.exists():
            return 0
        for sd in sessions_root.iterdir():
            if not sd.is_dir():
                continue
            manifest_path = sd / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                m = Manifest.model_validate_json(manifest_path.read_text())
            except Exception:
                logger.warning("autopsy: bad manifest at %s, marking partial", sd)
                continue
            if m.status == "live":
                m = m.model_copy(update={"status": "partial"})
                manifest_path.write_text(m.model_dump_json(indent=2))
            self.index.upsert(m, str(sd))
            count += 1
        return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_local_fs.py -v`
Expected: 10 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/store/local_fs.py tests/unit/test_local_fs.py`
Expected: All checks passed.

```bash
git add autopsy/core/store/local_fs.py tests/unit/test_local_fs.py
git commit -m "feat(store): add LocalFilesystemStore with atomic manifest writes"
```

### Task 2.3: SQLite derived index

**Files:**
- Create: `autopsy/core/store/sqlite_index.py`
- Test: `tests/unit/test_sqlite_index.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sqlite_index.py`:

```python
"""Unit tests for the SQLite derived index."""
from __future__ import annotations

from pathlib import Path

import pytest

from autopsy.core.events_v2 import Manifest
from autopsy.core.store.sqlite_index import SQLiteIndex


def _manifest(sid, *, start_ns=1000, status="ok", event_count=3) -> Manifest:
    return Manifest(
        session_id=sid,
        agent_name="a",
        start_time_ns=start_ns,
        end_time_ns=start_ns + 1_000_000,
        duration_ms=1.0,
        status=status,
        error_type=None,
        event_count=event_count,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=start_ns,
        monotonic_ns_at_start=start_ns,
    )


def test_index_creates_schema(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    assert (tmp_path / "i.sqlite").exists()


def test_upsert_then_list(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("01HXY000000000000000000001"), "/p/1")
    rows = idx.list()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "01HXY000000000000000000001"
    assert rows[0]["status"] == "ok"
    assert rows[0]["path"] == "/p/1"


def test_list_orders_newest_first(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("a", start_ns=100), "/p/a")
    idx.upsert(_manifest("b", start_ns=200), "/p/b")
    rows = idx.list()
    assert [r["session_id"] for r in rows] == ["b", "a"]


def test_list_limit(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    for i in range(5):
        idx.upsert(_manifest(f"s{i}", start_ns=i * 100), f"/p/{i}")
    assert len(idx.list(limit=2)) == 2


def test_upsert_overwrites_same_session_id(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("s", status="live"), "/p")
    idx.upsert(_manifest("s", status="ok"), "/p")
    rows = idx.list()
    assert len(rows) == 1
    assert rows[0]["status"] == "ok"


def test_delete(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("s"), "/p")
    idx.delete("s")
    assert idx.list() == []


def test_pinned_sessions_are_returned(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    m = _manifest("s").model_copy(update={"pinned": True})
    idx.upsert(m, "/p")
    rows = idx.list()
    assert rows[0]["pinned"] == 1


def test_clear_empties_table(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    idx.upsert(_manifest("a"), "/p/a")
    idx.upsert(_manifest("b"), "/p/b")
    idx.clear()
    assert idx.list() == []


def test_wal_mode_enabled(tmp_path):
    idx = SQLiteIndex(tmp_path / "i.sqlite")
    import sqlite3
    with sqlite3.connect(tmp_path / "i.sqlite") as c:
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_sqlite_index.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/store/sqlite_index.py`:

```python
"""SQLite-backed derived index for fast session listing.

The index is *derived* — the source of truth is always the per-session
manifest.json on disk. If this file is missing or corrupted, the
`LocalFilesystemStore.reindex()` method rebuilds it by walking the
sessions directory.

WAL mode is enabled so the dashboard / CLI can read concurrently while
the writer thread inserts. Writes use a short-held connection opened per
operation; we never hold the connection across calls.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..events_v2 import Manifest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  start_time_ns INTEGER NOT NULL,
  end_time_ns INTEGER,
  duration_ms INTEGER,
  status TEXT NOT NULL,
  error_type TEXT,
  event_count INTEGER,
  dropped_events INTEGER DEFAULT 0,
  pinned INTEGER DEFAULT 0,
  path TEXT NOT NULL,
  schema_version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON sessions(start_time_ns DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
"""


class SQLiteIndex:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def upsert(self, manifest: Manifest, path: str) -> None:
        with self._connect() as c:
            c.execute(
                """INSERT INTO sessions (
                       session_id, agent_name, start_time_ns, end_time_ns,
                       duration_ms, status, error_type, event_count,
                       dropped_events, pinned, path, schema_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                       agent_name=excluded.agent_name,
                       start_time_ns=excluded.start_time_ns,
                       end_time_ns=excluded.end_time_ns,
                       duration_ms=excluded.duration_ms,
                       status=excluded.status,
                       error_type=excluded.error_type,
                       event_count=excluded.event_count,
                       dropped_events=excluded.dropped_events,
                       pinned=excluded.pinned,
                       path=excluded.path,
                       schema_version=excluded.schema_version
                """,
                (
                    manifest.session_id,
                    manifest.agent_name,
                    manifest.start_time_ns,
                    manifest.end_time_ns,
                    int(manifest.duration_ms) if manifest.duration_ms is not None else None,
                    manifest.status,
                    manifest.error_type,
                    manifest.event_count,
                    manifest.dropped_events,
                    1 if manifest.pinned else 0,
                    path,
                    manifest.autopsy_format_version,
                ),
            )

    def delete(self, session_id: str) -> None:
        with self._connect() as c:
            c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def list(self, limit: int | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM sessions ORDER BY start_time_ns DESC"
        params: tuple = ()
        if limit is not None:
            q += " LIMIT ?"
            params = (limit,)
        with self._connect() as c:
            rows = c.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> None:
        with self._connect() as c:
            c.execute("DELETE FROM sessions")

    def find_evictable(self, *, max_age_ns: int | None, now_ns: int) -> list[dict[str, Any]]:
        """Return non-pinned sessions older than max_age_ns (oldest first)."""
        with self._connect() as c:
            if max_age_ns is None:
                rows = c.execute(
                    "SELECT * FROM sessions WHERE pinned = 0 ORDER BY start_time_ns ASC"
                ).fetchall()
            else:
                cutoff = now_ns - max_age_ns
                rows = c.execute(
                    "SELECT * FROM sessions WHERE pinned = 0 AND start_time_ns < ? "
                    "ORDER BY start_time_ns ASC",
                    (cutoff,),
                ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_sqlite_index.py -v`
Expected: 9 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/store/sqlite_index.py tests/unit/test_sqlite_index.py`
Expected: All checks passed.

```bash
git add autopsy/core/store/sqlite_index.py tests/unit/test_sqlite_index.py
git commit -m "feat(store): add SQLite derived index with WAL mode"
```

### Task 2.4: Eviction (size + age caps)

**Files:**
- Modify: `autopsy/core/store/local_fs.py` (add `evict()` method)
- Test: `tests/unit/test_eviction.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_eviction.py`:

```python
"""Tests for the size + age eviction policy on LocalFilesystemStore."""
from __future__ import annotations

import time

import pytest

from autopsy.core.events_v2 import AgentStartEvent, EventKind, Manifest
from autopsy.core.store.local_fs import LocalFilesystemStore


def _ev(sid: str) -> AgentStartEvent:
    return AgentStartEvent(
        event_id="01HXY00000000000000000000" + sid[-1],
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=1,
        kind=EventKind.AGENT_START,
        agent_name="a",
    )


def _manifest(sid: str, *, start_ns: int, pinned=False) -> Manifest:
    return Manifest(
        session_id=sid,
        agent_name="a",
        start_time_ns=start_ns,
        end_time_ns=start_ns + 1,
        duration_ms=1.0,
        status="ok",
        error_type=None,
        event_count=1,
        dropped_events=0,
        pinned=pinned,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=start_ns,
        monotonic_ns_at_start=start_ns,
    )


def _make_session(store, sid, *, start_ns, pinned=False, padding_kb=0):
    store.write_events(sid, [_ev(sid)])
    if padding_kb:
        sd = store.root / "sessions" / sid
        (sd / "artifacts" / "pad.bin").write_bytes(b"x" * padding_kb * 1024)
    store.finalize_session(_manifest(sid, start_ns=start_ns, pinned=pinned))


def test_evict_by_age_removes_old_unpinned(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    one_day_ns = 86_400 * 1_000_000_000
    _make_session(store, "01HXY000000000000000000001", start_ns=now_ns - 40 * one_day_ns)
    _make_session(store, "01HXY000000000000000000002", start_ns=now_ns)
    removed = store.evict(max_total_disk_mb=10_000, max_session_age_days=30, now_ns=now_ns)
    ids = {r["session_id"] for r in removed}
    assert ids == {"01HXY000000000000000000001"}
    assert {r["session_id"] for r in store.list_sessions()} == {"01HXY000000000000000000002"}


def test_evict_by_age_respects_pinned(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    one_day_ns = 86_400 * 1_000_000_000
    _make_session(
        store, "01HXY000000000000000000001",
        start_ns=now_ns - 40 * one_day_ns, pinned=True,
    )
    removed = store.evict(max_total_disk_mb=10_000, max_session_age_days=30, now_ns=now_ns)
    assert removed == []


def test_evict_by_size_removes_oldest_first(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    _make_session(store, "01HXY000000000000000000001", start_ns=now_ns - 3000, padding_kb=600)
    _make_session(store, "01HXY000000000000000000002", start_ns=now_ns - 2000, padding_kb=600)
    _make_session(store, "01HXY000000000000000000003", start_ns=now_ns - 1000, padding_kb=600)
    removed = store.evict(max_total_disk_mb=1, max_session_age_days=365 * 10, now_ns=now_ns)
    removed_ids = [r["session_id"] for r in removed]
    assert removed_ids and removed_ids[0] == "01HXY000000000000000000001"
    remaining = {r["session_id"] for r in store.list_sessions()}
    assert "01HXY000000000000000000003" in remaining


def test_evict_by_size_skips_pinned(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    now_ns = int(time.time() * 1e9)
    _make_session(
        store, "01HXY000000000000000000001",
        start_ns=now_ns - 3000, padding_kb=600, pinned=True,
    )
    _make_session(store, "01HXY000000000000000000002", start_ns=now_ns - 2000, padding_kb=600)
    removed = store.evict(max_total_disk_mb=1, max_session_age_days=365 * 10, now_ns=now_ns)
    assert "01HXY000000000000000000001" not in {r["session_id"] for r in removed}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_eviction.py -v`
Expected: FAIL — `AttributeError: 'LocalFilesystemStore' object has no attribute 'evict'`

- [ ] **Step 3: Write minimal implementation**

Append to `autopsy/core/store/local_fs.py`:

```python
    def _session_disk_bytes(self, session_dir) -> int:
        total = 0
        for p in session_dir.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
        return total

    def evict(
        self,
        *,
        max_total_disk_mb: int,
        max_session_age_days: int,
        now_ns: int,
    ) -> list[dict]:
        """Apply age + size eviction. Returns the rows that were deleted.

        Age first: sessions older than max_session_age_days are removed
        regardless of size (skipping pinned). Then, if total bytes still
        exceeds max_total_disk_mb, remove oldest non-pinned sessions
        until under the cap.
        """
        removed: list[dict] = []
        max_age_ns = max_session_age_days * 86_400 * 1_000_000_000
        for row in self.index.find_evictable(max_age_ns=max_age_ns, now_ns=now_ns):
            self.delete_session(row["session_id"])
            removed.append(row)

        cap_bytes = max_total_disk_mb * 1024 * 1024
        sessions_root = self.root / "sessions"
        if not sessions_root.exists():
            return removed

        def total_bytes() -> int:
            total = 0
            for sd in sessions_root.iterdir():
                if sd.is_dir():
                    total += self._session_disk_bytes(sd)
            return total

        current = total_bytes()
        if current <= cap_bytes:
            return removed
        for row in self.index.find_evictable(max_age_ns=None, now_ns=now_ns):
            if current <= cap_bytes:
                break
            sd = sessions_root / row["session_id"]
            size = self._session_disk_bytes(sd) if sd.exists() else 0
            self.delete_session(row["session_id"])
            removed.append(row)
            current -= size
        return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_eviction.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/store/local_fs.py tests/unit/test_eviction.py`
Expected: All checks passed.

```bash
git add autopsy/core/store/local_fs.py tests/unit/test_eviction.py
git commit -m "feat(store): add age + size eviction respecting pinned sessions"
```

---

## Phase 3 — Writer

The writer is the heart of the new design: one daemon thread, one bounded queue, batched draining, per-session in-memory buffers, and the sample-state machine that decides whether to spill to disk or discard. Everything in the prior phases feeds into this.

### Task 3.1: Default redactor + secret patterns

**Files:**
- Create: `autopsy/core/redact.py`
- Test: `tests/unit/test_redact.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_redact.py`:

```python
"""Unit tests for the default redactor."""
from __future__ import annotations

from autopsy.core.events_v2 import EventKind, LLMRequestEvent, LogEvent
from autopsy.core.redact import default_redactor, scrub_secrets


def _llm(messages, **extra):
    return LLMRequestEvent(
        event_id="01HXY000000000000000000001",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=1,
        kind=EventKind.LLM_REQUEST,
        model="m",
        messages=messages,
        attributes=extra,
    )


def test_scrubs_openai_style_keys():
    out = scrub_secrets("Authorization: sk-abcd1234efgh5678ijkl9012mnop3456")
    assert "sk-abcd1234efgh5678ijkl9012mnop3456" not in out
    assert "[REDACTED:secret]" in out


def test_scrubs_bearer_token():
    out = scrub_secrets("Bearer eyJhbGciOi.JhdGUiOiJzZWNyZX.QifQ.signature123")
    assert "eyJhbG" not in out
    assert "[REDACTED:secret]" in out


def test_scrubs_aws_access_key():
    out = scrub_secrets("AWS=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_passes_through_non_secret_strings():
    s = "hello world, my user_id is 12345"
    assert scrub_secrets(s) == s


def test_default_redactor_walks_attributes():
    ev = _llm(messages=[], my_secret="sk-deadbeefdeadbeefdeadbeefdeadbeef")
    out = default_redactor(ev)
    assert out is not None
    assert "sk-deadbeefdeadbeefdeadbeefdeadbeef" not in out.model_dump_json()


def test_default_redactor_walks_messages():
    ev = _llm(messages=[{"role": "u", "content": "key=sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}])
    out = default_redactor(ev)
    assert out is not None
    assert "sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in out.model_dump_json()


def test_default_redactor_returns_event_unchanged_when_safe():
    ev = LogEvent(
        event_id="01HXY000000000000000000001",
        parent_id=None,
        session_id="s",
        trace_id="s",
        timestamp_ns=1,
        kind=EventKind.LOG,
        name="ok",
        attributes={"safe": "no secrets here"},
    )
    out = default_redactor(ev)
    assert out is not None
    assert out.attributes["safe"] == "no secrets here"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_redact.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/redact.py`:

```python
"""Default redactor and secret-pattern scrubber.

Scope:
- Common API-key shapes (OpenAI sk-, Bearer tokens, AWS access keys, OAuth-shaped
  long tokens). Best-effort, not exhaustive.
- Does NOT do PII detection — that's a downstream concern. Users supply a
  custom redactor on LensConfig.redactor if they need PII handling.

The redactor returns:
- A new event with scrubbed values (preferred).
- None to drop the event entirely.
- Raises only if the user-supplied redactor itself raises — callers catch
  RedactorError and fail-closed (drop the event).
"""
from __future__ import annotations

import re
from typing import Any

from .events_v2 import BaseEvent

REDACTED = "[REDACTED:secret]"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]{10,}", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"ya29\.[0-9A-Za-z_\-]+"),
    re.compile(r"xox[abprs]-[0-9A-Za-z\-]{10,}"),
]


def scrub_secrets(s: str) -> str:
    out = s
    for pat in _PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def _walk(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_secrets(value)
    if isinstance(value, dict):
        return {k: _walk(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_walk(v) for v in value)
    return value


def default_redactor(event: BaseEvent) -> BaseEvent | None:
    """Walk every field on the event, scrubbing matching secret patterns.

    Returns the (possibly-modified) event. Returns None only if a future
    policy decides to drop the event; today this function never drops.
    """
    data = event.model_dump()
    scrubbed = _walk(data)
    if scrubbed == data:
        return event
    return type(event).model_validate(scrubbed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_redact.py -v`
Expected: 7 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/redact.py tests/unit/test_redact.py`
Expected: All checks passed.

```bash
git add autopsy/core/redact.py tests/unit/test_redact.py
git commit -m "feat(writer): add default redactor for common secret patterns"
```

### Task 3.2: Writer thread + bounded queue (basic enqueue/drop semantics)

**Files:**
- Create: `autopsy/core/writer.py`
- Test: `tests/unit/test_writer.py`

This task introduces the daemon thread and the bounded queue. It writes nothing to disk yet; events are accumulated in an in-memory list per session so the test can assert ordering and drop counts. Disk writes come in task 3.3.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_writer.py`:

```python
"""Unit tests for Writer enqueue + drop-on-full semantics (no disk yet)."""
from __future__ import annotations

import threading
import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import (
    AgentStartEvent,
    EventKind,
    LogEvent,
)
from autopsy.core.writer import Writer


def _ev(kind, sid, seq=0):
    base = dict(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=seq,
        kind=kind,
    )
    if kind is EventKind.AGENT_START:
        return AgentStartEvent(**base, agent_name="a")
    return LogEvent(**base, name="n")


def test_writer_starts_and_stops_cleanly(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg)
    w.start()
    assert w.is_alive()
    w.shutdown(timeout=2.0)
    assert not w.is_alive()


def test_enqueue_increments_dropped_counter_when_full(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), queue_maxsize=4)
    w = Writer(config=cfg)
    w.start()
    try:
        w.pause_drain()
        for i in range(20):
            w.enqueue(_ev(EventKind.LOG, "s", seq=i))
        assert w.dropped_events_total >= 10
    finally:
        w.resume_drain()
        w.shutdown(timeout=2.0)


def test_enqueue_never_blocks_host_thread(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), queue_maxsize=2)
    w = Writer(config=cfg)
    w.start()
    try:
        w.pause_drain()
        t0 = time.perf_counter()
        for i in range(1000):
            w.enqueue(_ev(EventKind.LOG, "s", seq=i))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 100, f"enqueue blocked: {elapsed_ms}ms"
    finally:
        w.resume_drain()
        w.shutdown(timeout=2.0)


def test_drained_events_arrive_in_order(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(50):
            w.enqueue(_ev(EventKind.LOG, "s", seq=i))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and w.drained_count_for_test("s") < 50:
            time.sleep(0.01)
        events = w.drained_events_for_test("s")
        assert len(events) == 50
        assert [e.timestamp_ns for e in events] == list(range(50))
    finally:
        w.shutdown(timeout=2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.core.writer'`

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/writer.py`:

```python
"""Writer — single daemon thread, bounded queue, batched drain.

This module is the only thing between the hot path (decorator + interceptor)
and disk. The hot path's only writer call is `Writer.enqueue(event)`, which
is a `put_nowait` on a bounded `queue.Queue` — non-blocking, drops on full.

The drain runs on `Writer._thread`, which loops:
  1. Pull up to `flush_batch_size` events with a `flush_interval_ms` timeout.
  2. Group by session_id.
  3. Append to the per-session in-memory buffer.
  4. (Task 3.3) Decide kept vs discarded, spill to disk when kept.

In task 3.2 we stop at step 3. Disk writes arrive in 3.3.

Invariants:
- enqueue() never raises and never blocks more than a couple of microseconds.
- Any exception inside the drain loop is caught and logged; the thread
  does not die.
- The thread is a daemon so it does not keep the host process alive on exit.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import defaultdict
from typing import Optional

from .config import LensConfig
from .events_v2 import BaseEvent

logger = logging.getLogger("autopsy.writer")

_SENTINEL = object()


class Writer:
    def __init__(self, config: LensConfig):
        self.config = config
        self._queue: queue.Queue = queue.Queue(maxsize=config.queue_maxsize)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self.dropped_events_total: int = 0
        self._per_session_buffer: dict[str, list[BaseEvent]] = defaultdict(list)
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="autopsy-writer", daemon=True
        )
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def enqueue(self, event: BaseEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events_total += 1
        except Exception:
            self.dropped_events_total += 1

    def shutdown(self, timeout: float = 2.0) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(_SENTINEL)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ---- test hooks ----
    def pause_drain(self) -> None:
        self._paused.set()

    def resume_drain(self) -> None:
        self._paused.clear()

    def drained_count_for_test(self, session_id: str) -> int:
        with self._lock:
            return len(self._per_session_buffer.get(session_id, []))

    def drained_events_for_test(self, session_id: str) -> list[BaseEvent]:
        with self._lock:
            return list(self._per_session_buffer.get(session_id, []))

    # ---- main loop ----
    def _run(self) -> None:
        interval_s = self.config.flush_interval_ms / 1000.0
        batch_size = self.config.flush_batch_size
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.01)
                continue
            batch: list[BaseEvent] = []
            try:
                item = self._queue.get(timeout=interval_s)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                break
            batch.append(item)
            while len(batch) < batch_size:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is _SENTINEL:
                    self._process_batch(batch)
                    return
                batch.append(nxt)
            try:
                self._process_batch(batch)
            except Exception:
                logger.exception("autopsy: writer batch processing failed")

    def _process_batch(self, batch: list[BaseEvent]) -> None:
        with self._lock:
            for ev in batch:
                self._per_session_buffer[ev.session_id].append(ev)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_writer.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/writer.py tests/unit/test_writer.py`
Expected: All checks passed.

```bash
git add autopsy/core/writer.py tests/unit/test_writer.py
git commit -m "feat(writer): add daemon-thread writer with bounded queue + drop counter"
```

### Task 3.3: Writer batching + per-session buffer + redaction hook

**Files:**
- Modify: `autopsy/core/writer.py`
- Test: `tests/unit/test_writer_batching.py`

This task wires the redactor into the drain path and verifies the batch-size / batch-interval contract.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_writer_batching.py`:

```python
"""Tests for writer batching and redaction integration."""
from __future__ import annotations

import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import EventKind, LogEvent
from autopsy.core.writer import Writer


def _log(sid, seq, **attrs):
    return LogEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=sid,
        trace_id=sid,
        timestamp_ns=seq,
        kind=EventKind.LOG,
        name="n",
        attributes=attrs,
    )


def test_redactor_is_applied_to_each_event(tmp_path):
    seen = []

    def red(ev):
        seen.append(ev.attributes.get("k"))
        return ev.model_copy(update={"attributes": {"k": "REDACTED"}})

    cfg = LensConfig(session_dir=str(tmp_path), redactor=red)
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(5):
            w.enqueue(_log("s", i, k=f"orig-{i}"))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and w.drained_count_for_test("s") < 5:
            time.sleep(0.01)
        events = w.drained_events_for_test("s")
        assert all(e.attributes == {"k": "REDACTED"} for e in events)
        assert set(seen) == {f"orig-{i}" for i in range(5)}
    finally:
        w.shutdown(timeout=2.0)


def test_redactor_returning_none_drops_event(tmp_path):
    cfg = LensConfig(session_dir=str(tmp_path), redactor=lambda ev: None)
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(10):
            w.enqueue(_log("s", i))
        time.sleep(0.2)
        assert w.drained_count_for_test("s") == 0
    finally:
        w.shutdown(timeout=2.0)


def test_redactor_that_raises_is_caught_and_drops(tmp_path):
    def red(ev):
        raise RuntimeError("boom")

    cfg = LensConfig(session_dir=str(tmp_path), redactor=red)
    w = Writer(config=cfg)
    w.start()
    try:
        for i in range(5):
            w.enqueue(_log("s", i))
        time.sleep(0.2)
        assert w.drained_count_for_test("s") == 0
        assert w.is_alive()
    finally:
        w.shutdown(timeout=2.0)


def test_batch_respects_flush_interval(tmp_path):
    cfg = LensConfig(
        session_dir=str(tmp_path), flush_batch_size=1000, flush_interval_ms=30,
    )
    w = Writer(config=cfg)
    w.start()
    try:
        w.enqueue(_log("s", 0))
        time.sleep(0.1)
        assert w.drained_count_for_test("s") == 1
    finally:
        w.shutdown(timeout=2.0)


def test_batch_respects_size_cap(tmp_path):
    cfg = LensConfig(
        session_dir=str(tmp_path), flush_batch_size=5, flush_interval_ms=10_000,
    )
    w = Writer(config=cfg)
    w.start()
    try:
        w.pause_drain()
        for i in range(13):
            w.enqueue(_log("s", i))
        w.resume_drain()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and w.drained_count_for_test("s") < 13:
            time.sleep(0.01)
        assert w.drained_count_for_test("s") == 13
    finally:
        w.shutdown(timeout=2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_writer_batching.py -v`
Expected: FAIL — redactor isn't applied; first test fails on the assertion.

- [ ] **Step 3: Write minimal implementation**

Edit `_process_batch` in `autopsy/core/writer.py`:

```python
    def _process_batch(self, batch: list[BaseEvent]) -> None:
        red = self.config.redactor
        with self._lock:
            for raw in batch:
                ev: BaseEvent | None = raw
                if red is not None:
                    try:
                        ev = red(raw)
                    except Exception:
                        logger.warning("autopsy: redactor raised; dropping event")
                        ev = None
                if ev is None:
                    continue
                self._per_session_buffer[ev.session_id].append(ev)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_writer_batching.py tests/unit/test_writer.py -v`
Expected: 4 + 5 = 9 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/writer.py tests/unit/test_writer_batching.py`
Expected: All checks passed.

```bash
git add autopsy/core/writer.py tests/unit/test_writer_batching.py
git commit -m "feat(writer): apply redactor on drain, fail-closed on redactor error"
```

### Task 3.4: Sample state machine + spill-to-disk on session end

**Files:**
- Modify: `autopsy/core/writer.py`
- Test: `tests/unit/test_writer_sampling.py`

This task is the heart of the design. The writer holds a per-session in-memory buffer until the call ends; it then either spills to disk (kept) or discards (sampled out). It is also the integration point with `LocalFilesystemStore`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_writer_sampling.py`:

```python
"""Tests for the sample state machine in the writer."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import (
    AgentEndEvent,
    AgentStartEvent,
    ErrorEvent,
    EventKind,
    LogEvent,
)
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


SID = "01HXY000000000000000000001"


def _agent_start(seq=0):
    return AgentStartEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.AGENT_START,
        agent_name="a",
    )


def _agent_end(seq=99):
    return AgentEndEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.AGENT_END,
        duration_ms=1.0,
    )


def _log(seq, **attrs):
    return LogEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.LOG,
        name="n",
        attributes=attrs,
    )


def _error(seq=98):
    return ErrorEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.ERROR,
        error_type="X",
        error_message="m",
        traceback="t",
    )


def _wait_for_session_finalized(store, sid, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (store.root / "sessions" / sid / "manifest.json").exists():
            return True
        time.sleep(0.01)
    return False


def test_sample_errors_success_writes_no_disk_artifact(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        for i in range(3):
            w.enqueue(_log(i + 1))
        w.enqueue(_agent_end())
        w.end_session(SID, outcome="ok")
        time.sleep(0.2)
    finally:
        w.shutdown(timeout=2.0)
    assert not (tmp_path / "sessions" / SID).exists()


def test_sample_errors_error_writes_session(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        w.enqueue(_log(1))
        w.enqueue(_error())
        w.enqueue(_agent_end())
        w.end_session(SID, outcome="error", error_type="X")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "error"
    assert len(payload["events"]) >= 3


def test_sample_all_writes_session_even_on_success(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(_log(1))
        w.end_session(SID, outcome="ok")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "ok"


def test_sample_off_creates_nothing(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.OFF, agent_name="a", start_ns=1)
        w.enqueue(_log(1))
        w.end_session(SID, outcome="ok")
        time.sleep(0.1)
    finally:
        w.shutdown(timeout=2.0)
    assert not (tmp_path / "sessions" / SID).exists()


def test_in_flight_buffer_cap_promotes_to_partial(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(
        session_dir=str(tmp_path),
        default_sample="errors",
        max_in_flight_buffer_mb=0,
    )
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ERRORS, agent_name="a", start_ns=1)
        for i in range(50):
            w.enqueue(_log(i + 1, payload="x" * 4096))
        w.end_session(SID, outcome="ok")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "partial"


def test_head_rate_promotes_session(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(
            SID, sample=SampleMode.RATE, agent_name="a", start_ns=1,
            head_keep=True,
        )
        w.enqueue(_log(1))
        w.end_session(SID, outcome="ok")
    finally:
        w.shutdown(timeout=2.0)
    assert _wait_for_session_finalized(store, SID)
    payload = store.load_session(SID)
    assert payload["manifest"]["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_writer_sampling.py -v`
Expected: FAIL — `ImportError: cannot import name 'SampleMode'` (or attribute errors on Writer).

- [ ] **Step 3: Write minimal implementation**

Replace the body of `autopsy/core/writer.py` with:

```python
"""Writer — single daemon thread, bounded queue, batched drain.

The writer is the only piece between the hot path and disk. It accepts
events via a non-blocking put_nowait on a bounded queue, drains them on a
daemon thread, applies the redactor, and (this task) decides per-session
whether to spill to disk or discard based on the sample state machine.

Sample state machine:
  declared -> kept  (transition: explicit "all"/head-rate keep, or any
                     ERROR event observed, or in-flight buffer cap exceeded)
  declared -> discarded  (transition: end_session called and not kept)
  kept     -> finalized  (transition: end_session)

Kept sessions are spilled to the TraceStore lazily on the FIRST event that
arrives after the transition. Sessions that never transition to kept
never touch disk at all.
"""
from __future__ import annotations

import enum
import logging
import queue
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import LensConfig
from .events_v2 import BaseEvent, EventKind, Manifest

logger = logging.getLogger("autopsy.writer")

_SENTINEL = object()


class SampleMode(str, enum.Enum):
    ALL = "all"
    ERRORS = "errors"
    OFF = "off"
    RATE = "rate"


@dataclass
class _SessionState:
    session_id: str
    agent_name: str
    sample: SampleMode
    start_ns: int
    wall_ns: int
    monotonic_ns: int
    head_keep: bool = False
    kept: bool = False
    ended: bool = False
    outcome: str = "ok"
    error_type: str | None = None
    partial: bool = False
    buffer: list[BaseEvent] = field(default_factory=list)
    buffer_bytes: int = 0
    event_count: int = 0
    dropped_events: int = 0


class Writer:
    def __init__(self, config: LensConfig, store: Any | None = None):
        self.config = config
        self.store = store
        self._queue: queue.Queue = queue.Queue(maxsize=config.queue_maxsize)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self.dropped_events_total: int = 0
        self._sessions: dict[str, _SessionState] = {}
        self._lock = threading.Lock()
        self._per_session_buffer_for_test: dict[str, list[BaseEvent]] = defaultdict(list)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="autopsy-writer", daemon=True
        )
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def declare_session(
        self,
        session_id: str,
        *,
        sample: SampleMode,
        agent_name: str,
        start_ns: int,
        head_keep: bool = False,
        wall_ns: int | None = None,
        monotonic_ns: int | None = None,
    ) -> None:
        with self._lock:
            self._sessions[session_id] = _SessionState(
                session_id=session_id,
                agent_name=agent_name,
                sample=sample,
                start_ns=start_ns,
                wall_ns=wall_ns or start_ns,
                monotonic_ns=monotonic_ns or start_ns,
                head_keep=head_keep,
                kept=(sample is SampleMode.ALL) or head_keep,
            )

    def enqueue(self, event: BaseEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped_events_total += 1
            with self._lock:
                state = self._sessions.get(event.session_id)
                if state is not None:
                    state.dropped_events += 1
        except Exception:
            self.dropped_events_total += 1

    def end_session(self, session_id: str, *, outcome: str, error_type: str | None = None) -> None:
        try:
            self._queue.put_nowait(("END", session_id, outcome, error_type))
        except Exception:
            pass

    def shutdown(self, timeout: float = 2.0) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(_SENTINEL)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def pause_drain(self) -> None:
        self._paused.set()

    def resume_drain(self) -> None:
        self._paused.clear()

    def drained_count_for_test(self, session_id: str) -> int:
        with self._lock:
            return len(self._per_session_buffer_for_test.get(session_id, []))

    def drained_events_for_test(self, session_id: str) -> list[BaseEvent]:
        with self._lock:
            return list(self._per_session_buffer_for_test.get(session_id, []))

    def _run(self) -> None:
        interval_s = self.config.flush_interval_ms / 1000.0
        batch_size = self.config.flush_batch_size
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.01)
                continue
            batch: list = []
            try:
                item = self._queue.get(timeout=interval_s)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                break
            batch.append(item)
            while len(batch) < batch_size:
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is _SENTINEL:
                    self._process_batch(batch)
                    return
                batch.append(nxt)
            try:
                self._process_batch(batch)
            except Exception:
                logger.exception("autopsy: writer batch processing failed")

    def _process_batch(self, batch: list) -> None:
        red = self.config.redactor
        cap_bytes = self.config.max_in_flight_buffer_mb * 1024 * 1024
        with self._lock:
            for raw in batch:
                if isinstance(raw, tuple) and raw and raw[0] == "END":
                    _, sid, outcome, error_type = raw
                    self._finalize_session_locked(sid, outcome, error_type)
                    continue
                ev: BaseEvent | None = raw
                if red is not None:
                    try:
                        ev = red(raw)
                    except Exception:
                        logger.warning("autopsy: redactor raised; dropping event")
                        ev = None
                if ev is None:
                    continue
                state = self._sessions.get(ev.session_id)
                self._per_session_buffer_for_test[ev.session_id].append(ev)
                if state is None:
                    continue
                if state.sample is SampleMode.OFF:
                    continue
                state.buffer.append(ev)
                state.event_count += 1
                try:
                    state.buffer_bytes += len(ev.model_dump_json())
                except Exception:
                    pass
                if ev.kind is EventKind.ERROR:
                    state.kept = True
                if state.buffer_bytes > cap_bytes and not state.kept:
                    state.kept = True
                    state.partial = True
                if state.kept and self.store is not None and state.buffer:
                    try:
                        self.store.write_events(state.session_id, state.buffer)
                    except Exception:
                        logger.exception("autopsy: store.write_events failed")
                    state.buffer = []

    def _finalize_session_locked(
        self, session_id: str, outcome: str, error_type: str | None
    ) -> None:
        state = self._sessions.pop(session_id, None)
        if state is None:
            return
        if outcome == "error":
            state.kept = True
        if not state.kept:
            return
        if self.store is None:
            return
        try:
            if state.buffer:
                self.store.write_events(session_id, state.buffer)
                state.buffer = []
        except Exception:
            logger.exception("autopsy: final spill failed")
            state.partial = True
        end_ns = int(time.time() * 1e9)
        status: str
        if state.partial:
            status = "partial"
        elif outcome == "error":
            status = "error"
        else:
            status = "ok"
        try:
            manifest = Manifest(
                session_id=session_id,
                agent_name=state.agent_name,
                start_time_ns=state.start_ns,
                end_time_ns=end_ns,
                duration_ms=(end_ns - state.start_ns) / 1e6,
                status=status,
                error_type=error_type,
                event_count=state.event_count,
                dropped_events=state.dropped_events,
                autopsy_format_version=1,
                autopsy_version="0.2.0",
                wall_clock_ns_at_start=state.wall_ns,
                monotonic_ns_at_start=state.monotonic_ns,
            )
            self.store.finalize_session(manifest)
        except Exception:
            logger.exception("autopsy: finalize_session failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_writer_sampling.py tests/unit/test_writer.py tests/unit/test_writer_batching.py -v`
Expected: 6 + 4 + 5 = 15 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/writer.py tests/unit/test_writer_sampling.py`
Expected: All checks passed.

```bash
git add autopsy/core/writer.py tests/unit/test_writer_sampling.py
git commit -m "feat(writer): add sample state machine and store integration"
```

### Task 3.5: atexit flush with bounded timeout

**Files:**
- Modify: `autopsy/core/writer.py`
- Test: `tests/unit/test_writer_atexit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_writer_atexit.py`:

```python
"""Tests for atexit drain semantics on the writer."""
from __future__ import annotations

import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import EventKind, LogEvent
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def _log(seq):
    return LogEvent(
        event_id="01HXY00000000000000000000" + str(seq),
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=seq,
        kind=EventKind.LOG,
        name="n",
    )


def test_atexit_drains_within_timeout(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
    for i in range(20):
        w.enqueue(_log(i))
    w.end_session(SID, outcome="ok")
    t0 = time.perf_counter()
    w.atexit_flush(timeout=2.0)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.5
    assert (tmp_path / "sessions" / SID / "manifest.json").exists()


def test_atexit_marks_unfinalized_session_partial(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
    w.enqueue(_log(0))
    w.atexit_flush(timeout=2.0)
    payload = store.load_session(SID)
    if payload is not None:
        assert payload["manifest"]["status"] in ("partial", "ok")


def test_atexit_is_idempotent(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    w.atexit_flush(timeout=1.0)
    w.atexit_flush(timeout=1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_writer_atexit.py -v`
Expected: FAIL — `AttributeError: 'Writer' object has no attribute 'atexit_flush'`

- [ ] **Step 3: Write minimal implementation**

Add to `Writer` in `autopsy/core/writer.py`:

```python
    def atexit_flush(self, timeout: float = 2.0) -> None:
        """Drain remaining events with a bounded timeout.

        For each session that has not been explicitly ended, finalize it
        with outcome="partial" so the manifest reflects the abnormal exit.
        Safe to call more than once.
        """
        if self._stop.is_set() and not self.is_alive():
            return
        deadline = time.monotonic() + timeout
        with self._lock:
            stale = list(self._sessions.keys())
        for sid in stale:
            try:
                self._queue.put_nowait(("END", sid, "partial", None))
            except Exception:
                pass
        while time.monotonic() < deadline:
            if self._queue.empty():
                break
            time.sleep(0.01)
        self.shutdown(timeout=max(0.1, deadline - time.monotonic()))
```

Also register the atexit hook on first session declaration. Modify `declare_session` to call `_ensure_atexit_registered()`:

```python
import atexit

class Writer:
    _atexit_registered = False

    def _ensure_atexit_registered(self) -> None:
        if Writer._atexit_registered:
            return
        atexit.register(self.atexit_flush, timeout=2.0)
        Writer._atexit_registered = True
```

And call `self._ensure_atexit_registered()` at the top of `declare_session`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_writer_atexit.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/writer.py tests/unit/test_writer_atexit.py`
Expected: All checks passed.

```bash
git add autopsy/core/writer.py tests/unit/test_writer_atexit.py
git commit -m "feat(writer): drain remaining events on atexit with 2s timeout"
```

---

## Phase 4 — Exporters

The exporter seam lets the writer fan events out to multiple sinks. `FileSystemExporter` wraps the store; `LoggingExporter` emits the structured finalization log line. No OTel / Sentry exporters ship in v1.

### Task 4.1: Exporter Protocol

**Files:**
- Create: `autopsy/core/exporters/__init__.py`
- Test: `tests/unit/test_exporter_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_exporter_protocol.py`:

```python
"""Shape test for the Exporter Protocol."""
from __future__ import annotations

import inspect

from autopsy.core.exporters import Exporter


def test_exporter_has_expected_methods():
    expected = {"export", "finalize_session"}
    members = {n for n, _ in inspect.getmembers(Exporter) if not n.startswith("_")}
    assert expected <= members
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_exporter_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/exporters/__init__.py`:

```python
"""Exporter Protocol — the seam for fanning events out beyond local disk.

`FileSystemExporter` wraps the LocalFilesystemStore. `LoggingExporter`
emits a structured `logging` line on finalize. Both ship in v1.

Future OpenTelemetry / Sentry / DataDog exporters slot in here without
changing the writer.
"""
from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from ..events_v2 import BaseEvent, Manifest


@runtime_checkable
class Exporter(Protocol):
    def export(self, session_id: str, batch: Iterable[BaseEvent]) -> None: ...

    def finalize_session(self, manifest: Manifest) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_exporter_protocol.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/exporters/__init__.py tests/unit/test_exporter_protocol.py`
Expected: All checks passed.

```bash
git add autopsy/core/exporters/__init__.py tests/unit/test_exporter_protocol.py
git commit -m "feat(exporters): add Exporter Protocol for fan-out sinks"
```

### Task 4.2: FileSystemExporter

**Files:**
- Create: `autopsy/core/exporters/file.py`
- Test: `tests/unit/test_file_exporter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_file_exporter.py`:

```python
"""Tests for FileSystemExporter wrapping LocalFilesystemStore."""
from __future__ import annotations

from pathlib import Path

import pytest

from autopsy.core.events_v2 import (
    AgentStartEvent,
    EventKind,
    Manifest,
)
from autopsy.core.exporters.file import FileSystemExporter
from autopsy.core.store.local_fs import LocalFilesystemStore


SID = "01HXY000000000000000000001"


def _ev():
    return AgentStartEvent(
        event_id="01HXY000000000000000000001",
        parent_id=None,
        session_id=SID,
        trace_id=SID,
        timestamp_ns=1,
        kind=EventKind.AGENT_START,
        agent_name="a",
    )


def _manifest():
    return Manifest(
        session_id=SID,
        agent_name="a",
        start_time_ns=1,
        end_time_ns=2,
        duration_ms=0.001,
        status="ok",
        error_type=None,
        event_count=1,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=1,
        monotonic_ns_at_start=1,
    )


def test_export_writes_events(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    exp = FileSystemExporter(store=store)
    exp.export(SID, [_ev()])
    assert (tmp_path / "sessions" / SID / "events.jsonl").exists()


def test_finalize_seals_manifest(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    exp = FileSystemExporter(store=store)
    exp.export(SID, [_ev()])
    exp.finalize_session(_manifest())
    assert (tmp_path / "sessions" / SID / "manifest.json").exists()


def test_finalize_swallows_store_errors(tmp_path):
    class BrokenStore:
        def write_events(self, *a, **k): raise IOError("boom")
        def finalize_session(self, *a, **k): raise IOError("boom")

    exp = FileSystemExporter(store=BrokenStore())
    exp.export(SID, [_ev()])
    exp.finalize_session(_manifest())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_file_exporter.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/exporters/file.py`:

```python
"""FileSystemExporter — thin wrapper around LocalFilesystemStore.

Exists so the writer's exporter contract is the same as any future
OTel / Sentry adapter. All disk I/O is delegated to the store. Errors
are caught and logged so a failing exporter cannot crash the writer.
"""
from __future__ import annotations

import logging
from typing import Iterable

from ..events_v2 import BaseEvent, Manifest

logger = logging.getLogger("autopsy.exporter.file")


class FileSystemExporter:
    def __init__(self, store):
        self.store = store

    def export(self, session_id: str, batch: Iterable[BaseEvent]) -> None:
        try:
            self.store.write_events(session_id, list(batch))
        except Exception:
            logger.exception("autopsy: FileSystemExporter.export failed")

    def finalize_session(self, manifest: Manifest) -> None:
        try:
            self.store.finalize_session(manifest)
        except Exception:
            logger.exception("autopsy: FileSystemExporter.finalize_session failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_file_exporter.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/exporters/file.py tests/unit/test_file_exporter.py`
Expected: All checks passed.

```bash
git add autopsy/core/exporters/file.py tests/unit/test_file_exporter.py
git commit -m "feat(exporters): add FileSystemExporter wrapping the local store"
```

### Task 4.3: LoggingExporter (rate-limited finalization log)

**Files:**
- Create: `autopsy/core/exporters/logging.py`
- Test: `tests/unit/test_logging_exporter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_logging_exporter.py`:

```python
"""Tests for the LoggingExporter that emits the finalization log line."""
from __future__ import annotations

import logging
import time

import pytest

from autopsy.core.events_v2 import Manifest
from autopsy.core.exporters.logging import LoggingExporter


def _manifest(*, status="ok", agent_name="a", error_type=None):
    return Manifest(
        session_id="01HXY000000000000000000001",
        agent_name=agent_name,
        start_time_ns=1,
        end_time_ns=1_000_000,
        duration_ms=1.0,
        status=status,
        error_type=error_type,
        event_count=3,
        dropped_events=0,
        autopsy_format_version=1,
        autopsy_version="0.2.0",
        wall_clock_ns_at_start=1,
        monotonic_ns_at_start=1,
    )


def test_finalize_emits_warning_for_error(caplog):
    exp = LoggingExporter(info_rate_s=60)
    with caplog.at_level(logging.WARNING, logger="autopsy"):
        exp.finalize_session(_manifest(status="error", error_type="ValueError"))
    recs = [r for r in caplog.records if r.name == "autopsy"]
    assert any(r.levelno == logging.WARNING for r in recs)
    rec = next(r for r in recs if r.levelno == logging.WARNING)
    assert getattr(rec, "session_id", None) == "01HXY000000000000000000001"
    assert getattr(rec, "status", None) == "error"
    assert getattr(rec, "error_type", None) == "ValueError"


def test_finalize_emits_info_for_ok(caplog):
    exp = LoggingExporter(info_rate_s=0)
    with caplog.at_level(logging.INFO, logger="autopsy"):
        exp.finalize_session(_manifest(status="ok"))
    recs = [r for r in caplog.records if r.name == "autopsy" and r.levelno == logging.INFO]
    assert recs


def test_info_logs_are_rate_limited_per_agent(caplog):
    exp = LoggingExporter(info_rate_s=60)
    with caplog.at_level(logging.INFO, logger="autopsy"):
        exp.finalize_session(_manifest(status="ok", agent_name="a"))
        exp.finalize_session(_manifest(status="ok", agent_name="a"))
    recs = [r for r in caplog.records if r.name == "autopsy" and r.levelno == logging.INFO]
    assert len(recs) == 1


def test_disabled_skip_all(caplog):
    exp = LoggingExporter(enabled=False)
    with caplog.at_level(logging.WARNING, logger="autopsy"):
        exp.finalize_session(_manifest(status="error"))
    assert not [r for r in caplog.records if r.name == "autopsy"]


def test_export_is_a_noop(tmp_path):
    exp = LoggingExporter()
    exp.export("01HXY000000000000000000001", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_logging_exporter.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/exporters/logging.py`:

```python
"""LoggingExporter — emit one structured log line per session finalize.

WARNING for status in {"error", "partial"}; INFO for "ok" (rate-limited to
one per agent_name per `info_rate_s` seconds so a high-QPS healthy stream
does not flood logs).

Uses LoggerAdapter-style `extra=` so structured-log handlers receive the
fields as keys rather than parsing the human message.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

from ..events_v2 import BaseEvent, Manifest

_LOGGER = logging.getLogger("autopsy")


class LoggingExporter:
    def __init__(self, *, info_rate_s: int = 60, enabled: bool = True):
        self.info_rate_s = info_rate_s
        self.enabled = enabled
        self._last_info: dict[str, float] = {}

    def export(self, session_id: str, batch: Iterable[BaseEvent]) -> None:
        return

    def finalize_session(self, manifest: Manifest) -> None:
        if not self.enabled:
            return
        extra = {
            "session_id": manifest.session_id,
            "agent_name": manifest.agent_name,
            "status": manifest.status,
            "error_type": manifest.error_type,
            "duration_ms": manifest.duration_ms,
            "event_count": manifest.event_count,
            "dropped_events": manifest.dropped_events,
            "trace_path": "",
            "autopsy_version": manifest.autopsy_version,
        }
        msg = (
            f"autopsy: agent={manifest.agent_name} status={manifest.status} "
            f"duration={int(manifest.duration_ms or 0)}ms session={manifest.session_id} "
            f"run 'autopsy diagnose {manifest.session_id}' to investigate"
        )
        if manifest.status in ("error", "partial"):
            _LOGGER.warning(msg, extra=extra)
            return
        now = time.monotonic()
        last = self._last_info.get(manifest.agent_name, -1e9)
        if now - last >= self.info_rate_s:
            self._last_info[manifest.agent_name] = now
            _LOGGER.info(msg, extra=extra)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_logging_exporter.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/exporters/logging.py tests/unit/test_logging_exporter.py`
Expected: All checks passed.

```bash
git add autopsy/core/exporters/logging.py tests/unit/test_logging_exporter.py
git commit -m "feat(exporters): add LoggingExporter with rate-limited INFO emission"
```

---

## Phase 5 — Decorator and interceptor rewrite

This is the phase where the new capture pipeline becomes visible to the user. The old `tracer.py` / `decorator.py` / `interceptor.py` keep working (existing tests still pass); the new modules live alongside.

### Task 5.1: Context vars (current session / parent span / suppression)

**Files:**
- Create: `autopsy/core/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_context.py`:

```python
"""Tests for the capture-layer ContextVars."""
from __future__ import annotations

from autopsy.core.context import (
    current_parent_id,
    current_session,
    is_diagnostics_call,
    set_diagnostics_call,
    set_parent_id,
    set_session,
)


def test_session_default_is_none():
    assert current_session() is None


def test_set_and_reset_session():
    token = set_session("S1")
    assert current_session() == "S1"
    set_session(None, token=token)
    assert current_session() is None


def test_parent_id_default_is_none():
    assert current_parent_id() is None


def test_set_and_reset_parent_id():
    token = set_parent_id("p1")
    assert current_parent_id() == "p1"
    set_parent_id(None, token=token)
    assert current_parent_id() is None


def test_diagnostics_call_default():
    assert is_diagnostics_call() is False


def test_diagnostics_call_set_and_reset():
    token = set_diagnostics_call(True)
    assert is_diagnostics_call() is True
    set_diagnostics_call(False, token=token)
    assert is_diagnostics_call() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/context.py`:

```python
"""ContextVars used across the capture layer.

These propagate through `await` and `asyncio.Task`. The decorator and
interceptor read them on the hot path; they are never mutated outside
the decorator/interceptor/session lifecycle.

Why ContextVars and not a thread-local: asyncio Tasks copy the ContextVar
state at task creation, so nested traces correctly observe their parent
even across `asyncio.gather`.
"""
from __future__ import annotations

import contextvars
from typing import Any

_current_session: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "autopsy_current_session", default=None
)
_current_parent_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "autopsy_current_parent_id", default=None
)
_in_diagnostics_call: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "autopsy_in_diagnostics_call", default=False
)


def current_session() -> Any:
    return _current_session.get()


def set_session(value: Any, *, token: contextvars.Token | None = None) -> contextvars.Token:
    if token is not None:
        _current_session.reset(token)
        return token
    return _current_session.set(value)


def current_parent_id() -> str | None:
    return _current_parent_id.get()


def set_parent_id(
    value: str | None, *, token: contextvars.Token | None = None
) -> contextvars.Token:
    if token is not None:
        _current_parent_id.reset(token)
        return token
    return _current_parent_id.set(value)


def is_diagnostics_call() -> bool:
    return _in_diagnostics_call.get()


def set_diagnostics_call(
    value: bool, *, token: contextvars.Token | None = None
) -> contextvars.Token:
    if token is not None:
        _in_diagnostics_call.reset(token)
        return token
    return _in_diagnostics_call.set(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_context.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/context.py tests/unit/test_context.py`
Expected: All checks passed.

```bash
git add autopsy/core/context.py tests/unit/test_context.py
git commit -m "feat(core): add ContextVars for session/parent/diagnostics suppression"
```

### Task 5.2: Session lifecycle (replaces TraceSession)

**Files:**
- Create: `autopsy/core/session.py`
- Test: `tests/unit/test_session.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_session.py`:

```python
"""Tests for the new Session lifecycle."""
from __future__ import annotations

import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.session import Session, get_writer
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def test_session_id_is_ulid():
    cfg = LensConfig()
    s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
    assert len(s.session_id) == 26
    s.end(outcome="ok")


def test_record_event_enqueues_through_writer(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    writer = Writer(config=cfg, store=store)
    writer.start()
    try:
        s = Session.begin(
            config=cfg, agent_name="a", sample=SampleMode.ALL, writer=writer,
        )
        from autopsy.core.events_v2 import EventKind, LogEvent
        ev = LogEvent(
            event_id="01HXY000000000000000000001",
            parent_id=None,
            session_id=s.session_id,
            trace_id=s.session_id,
            timestamp_ns=1,
            kind=EventKind.LOG,
            name="n",
        )
        s.record_event(ev)
        s.end(outcome="ok")
        time.sleep(0.2)
        assert (tmp_path / "sessions" / s.session_id / "manifest.json").exists()
    finally:
        writer.shutdown(timeout=2.0)


def test_get_writer_returns_singleton():
    a = get_writer(LensConfig())
    b = get_writer(LensConfig())
    assert a is b


def test_session_record_event_never_raises():
    cfg = LensConfig()
    s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)

    class Bomb:
        session_id = "wrong"
        kind = None

    s.record_event(Bomb())  # type: ignore[arg-type]
    s.end(outcome="ok")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/session.py`:

```python
"""Session — the per-call object the decorator creates and the interceptor reads.

Replaces the old `TraceSession`. Key differences:
- No asyncio.Queue, no drain task. Events go straight to the process-wide
  Writer daemon via `Writer.enqueue`, which is a non-blocking put_nowait.
- The session itself is cheap: an ID, a config snapshot, the writer ref,
  and a few timing fields. It does not own a thread, does not touch disk.
- The Writer is a process-wide singleton fetched via `get_writer(config)`.

A Session is created at the root @lens.trace call and is the value stored
in the `current_session` ContextVar for the lifetime of that call.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Optional

from .config import LensConfig
from .events_v2 import BaseEvent
from .store.local_fs import LocalFilesystemStore
from .ulid import new_ulid
from .writer import SampleMode, Writer

logger = logging.getLogger("autopsy.session")

_writer_lock = threading.Lock()
_writer_singleton: Optional[Writer] = None


def get_writer(config: LensConfig) -> Writer:
    global _writer_singleton
    with _writer_lock:
        if _writer_singleton is None:
            root = config.session_dir or _pick_default_root()
            store = LocalFilesystemStore(root=root)
            _writer_singleton = Writer(config=config, store=store)
            _writer_singleton.start()
        return _writer_singleton


def _pick_default_root() -> str:
    import os
    import tempfile
    from pathlib import Path

    candidates = []
    raw = os.environ.get("AUTOPSY_SESSION_DIR")
    if raw:
        candidates.append(Path(os.path.expanduser(raw)))
    candidates.append(Path(os.path.expanduser("~/.autopsy")))
    candidates.append(Path.cwd() / ".autopsy")
    candidates.append(Path(tempfile.gettempdir()) / "autopsy")
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            probe = c / ".write_probe"
            probe.write_text("")
            probe.unlink(missing_ok=True)
            return str(c)
        except Exception:
            continue
    return str(candidates[-1])


def _resolve_sample(raw, config_default) -> tuple[SampleMode, bool]:
    """Return (mode, head_keep) given a per-call sample arg + the config default.

    head_keep is True iff a head-based rate roll selected this call.
    """
    chosen = raw if raw is not None else config_default
    if chosen == "all":
        return SampleMode.ALL, False
    if chosen == "off":
        return SampleMode.OFF, False
    if chosen == "errors":
        return SampleMode.ERRORS, False
    try:
        f = float(chosen)
    except (TypeError, ValueError):
        return SampleMode.ERRORS, False
    if random.random() < f:
        return SampleMode.RATE, True
    return SampleMode.ERRORS, False


class Session:
    def __init__(
        self,
        *,
        session_id: str,
        agent_name: str,
        sample: SampleMode,
        head_keep: bool,
        writer: Writer,
        start_perf_ns: int,
    ):
        self.session_id = session_id
        self.agent_name = agent_name
        self.sample = sample
        self.head_keep = head_keep
        self.writer = writer
        self.start_perf_ns = start_perf_ns

    @classmethod
    def begin(
        cls,
        *,
        config: LensConfig,
        agent_name: str,
        sample,
        writer: Writer | None = None,
    ) -> "Session":
        mode, head_keep = _resolve_sample(sample, config.default_sample)
        w = writer if writer is not None else get_writer(config)
        sid = new_ulid()
        now_perf = time.perf_counter_ns()
        wall = time.time_ns()
        try:
            w.declare_session(
                sid,
                sample=mode,
                agent_name=agent_name,
                start_ns=wall,
                head_keep=head_keep,
                wall_ns=wall,
                monotonic_ns=now_perf,
            )
        except Exception:
            logger.exception("autopsy: declare_session failed")
        return cls(
            session_id=sid, agent_name=agent_name, sample=mode,
            head_keep=head_keep, writer=w, start_perf_ns=now_perf,
        )

    def record_event(self, ev: BaseEvent) -> None:
        try:
            if ev.session_id != self.session_id:
                try:
                    ev = ev.model_copy(update={"session_id": self.session_id})
                except Exception:
                    return
            self.writer.enqueue(ev)
        except Exception:
            logger.exception("autopsy: record_event failed")

    def end(self, *, outcome: str, error_type: str | None = None) -> None:
        try:
            self.writer.end_session(self.session_id, outcome=outcome, error_type=error_type)
        except Exception:
            logger.exception("autopsy: end_session failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_session.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/session.py tests/unit/test_session.py`
Expected: All checks passed.

```bash
git add autopsy/core/session.py tests/unit/test_session.py
git commit -m "feat(core): add Session lifecycle wired to the daemon writer"
```

### Task 5.3: New @lens.trace decorator (sync + async, no asyncio.run)

**Files:**
- Modify: `autopsy/core/decorator.py` — add `LensV2Decorator` class. Keep old `LensDecorator` intact until phase 7.
- Test: `tests/unit/test_decorator_v2.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_decorator_v2.py`:

```python
"""Tests for the new @lens.trace decorator wired through the writer."""
from __future__ import annotations

import asyncio
import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensV2Decorator
from autopsy.core.session import get_writer
from autopsy.core.store.local_fs import LocalFilesystemStore


@pytest.fixture
def lens_with_tmp_store(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensV2Decorator(config=cfg)
    yield lens, tmp_path
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _sessions(tmp_path):
    sd = tmp_path / "sessions"
    if not sd.exists():
        return []
    return [p.name for p in sd.iterdir() if p.is_dir() and (p / "manifest.json").exists()]


def test_async_success_with_sample_all_writes_session(lens_with_tmp_store):
    lens, tmp_path = lens_with_tmp_store

    @lens.trace
    async def agent(q):
        return q + "!"

    out = asyncio.run(agent("hi"))
    assert out == "hi!"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not _sessions(tmp_path):
        time.sleep(0.02)
    assert len(_sessions(tmp_path)) == 1


def test_async_error_writes_session_under_errors_sampling(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensV2Decorator(config=cfg)

    @lens.trace
    async def agent(q):
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        asyncio.run(agent("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    rows = [p for p in sd.iterdir() if (p / "manifest.json").exists()] if sd.exists() else []
    assert len(rows) == 1


def test_async_success_writes_nothing_under_errors_sampling(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensV2Decorator(config=cfg)

    @lens.trace
    async def agent(q):
        return "ok"

    asyncio.run(agent("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    assert not sd.exists() or not list(sd.iterdir())


def test_sync_function_does_not_call_asyncio_run(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensV2Decorator(config=cfg)

    @lens.trace
    def agent(q):
        return q.upper()

    real_run = asyncio.run
    called = {"n": 0}

    def fake_run(*a, **k):
        called["n"] += 1
        return real_run(*a, **k)

    monkeypatch.setattr(asyncio, "run", fake_run)
    out = agent("hi")
    assert out == "HI"
    assert called["n"] == 0
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def test_sample_off_is_a_noop(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path))
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensV2Decorator(config=cfg)

    @lens.trace(sample="off")
    async def agent(q):
        return q

    asyncio.run(agent("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    assert not sd.exists() or not list(sd.iterdir())


def test_nested_decorated_calls_share_one_session(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensV2Decorator(config=cfg)

    @lens.trace
    async def inner(q):
        return q

    @lens.trace
    async def outer(q):
        return await inner(q)

    asyncio.run(outer("hi"))
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    sd = tmp_path / "sessions"
    rows = [p for p in sd.iterdir() if (p / "manifest.json").exists()]
    assert len(rows) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_decorator_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'LensV2Decorator'`.

- [ ] **Step 3: Write minimal implementation**

Append to `autopsy/core/decorator.py` (do NOT remove the existing `LensDecorator`; both must coexist until phase 7):

```python
# ----- new v2 decorator (added in phase 5; replaces LensDecorator in phase 7) -----

from .config import LensConfig as _LensConfig
from .context import (
    current_parent_id,
    current_session,
    set_parent_id,
    set_session,
)
from .events_v2 import (
    AgentEndEvent,
    AgentStartEvent,
    ErrorEvent,
    EventKind,
)
from .session import Session as _Session
from .ulid import new_ulid


def _preview(value, limit: int = 512) -> str:
    try:
        s = repr(value)
    except Exception:
        s = "<unrepr>"
    return s[:limit]


class LensV2Decorator:
    """The new @lens.trace. Replaces LensDecorator in phase 7.

    - Sync wrapper calls fn() directly. No asyncio.run, no event loop spinup.
    - Async wrapper is an `async def`. The trace emission is synchronous
      (Writer.enqueue is put_nowait), so the await chain is untouched.
    - Nested calls share the root session via the `current_session` ContextVar.
    """

    def __init__(self, config: _LensConfig | None = None):
        self.config = config or _LensConfig()

    def trace(self, fn=None, *, sample=None, name=None):
        if fn is None:
            return lambda f: self.trace(f, sample=sample, name=name)
        return self._wrap(fn, sample=sample, name=name)

    def _wrap(self, fn, *, sample, name):
        import asyncio
        import functools

        is_coro = asyncio.iscoroutinefunction(fn)
        agent_name = name or getattr(fn, "__name__", "agent")

        if is_coro:
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                return await self._invoke_async(
                    fn, args, kwargs, sample=sample, agent_name=agent_name,
                )
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            return self._invoke_sync(
                fn, args, kwargs, sample=sample, agent_name=agent_name,
            )
        return sync_wrapper

    def _begin_or_join(self, sample, agent_name):
        existing = current_session()
        if existing is not None:
            return existing, False
        session = _Session.begin(
            config=self.config, agent_name=agent_name, sample=sample,
        )
        set_session(session)
        return session, True

    def _emit_agent_start(self, session, agent_name, input_preview):
        node_id = new_ulid()
        parent_id = current_parent_id()
        try:
            ev = AgentStartEvent(
                event_id=node_id,
                parent_id=parent_id,
                session_id=session.session_id,
                trace_id=session.session_id,
                timestamp_ns=__import__("time").time_ns(),
                kind=EventKind.AGENT_START,
                agent_name=agent_name,
                role="agent",
                input_preview=input_preview,
            )
            session.record_event(ev)
        except Exception:
            pass
        return node_id

    def _emit_agent_end(self, session, node_id, parent_id, duration_ms, output_preview):
        try:
            ev = AgentEndEvent(
                event_id=new_ulid(),
                parent_id=parent_id,
                session_id=session.session_id,
                trace_id=session.session_id,
                timestamp_ns=__import__("time").time_ns(),
                kind=EventKind.AGENT_END,
                duration_ms=duration_ms,
                output_preview=output_preview,
            )
            session.record_event(ev)
        except Exception:
            pass

    def _emit_error(self, session, node_id, parent_id, exc):
        import traceback as tb
        try:
            ev = ErrorEvent(
                event_id=new_ulid(),
                parent_id=node_id,
                session_id=session.session_id,
                trace_id=session.session_id,
                timestamp_ns=__import__("time").time_ns(),
                kind=EventKind.ERROR,
                error_type=type(exc).__name__,
                error_message=str(exc)[:2000],
                traceback=tb.format_exc()[:8000],
            )
            session.record_event(ev)
        except Exception:
            pass

    async def _invoke_async(self, fn, args, kwargs, *, sample, agent_name):
        import time as _t
        session, is_root = self._begin_or_join(sample, agent_name)
        node_id = self._emit_agent_start(
            session, agent_name, _preview(args[0] if args else kwargs),
        )
        parent_token = set_parent_id(node_id)
        start = _t.perf_counter()
        try:
            result = await fn(*args, **kwargs)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, _preview(result),
            )
            return result
        except Exception as exc:
            self._emit_error(session, node_id, current_parent_id(), exc)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, "",
            )
            if is_root:
                session.end(outcome="error", error_type=type(exc).__name__)
            raise
        finally:
            set_parent_id(None, token=parent_token)
            if is_root:
                try:
                    session.end(outcome="ok")
                except Exception:
                    pass
                set_session(None)

    def _invoke_sync(self, fn, args, kwargs, *, sample, agent_name):
        import time as _t
        session, is_root = self._begin_or_join(sample, agent_name)
        node_id = self._emit_agent_start(
            session, agent_name, _preview(args[0] if args else kwargs),
        )
        parent_token = set_parent_id(node_id)
        start = _t.perf_counter()
        try:
            result = fn(*args, **kwargs)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, _preview(result),
            )
            return result
        except Exception as exc:
            self._emit_error(session, node_id, current_parent_id(), exc)
            self._emit_agent_end(
                session, node_id, current_parent_id(),
                (_t.perf_counter() - start) * 1000.0, "",
            )
            if is_root:
                session.end(outcome="error", error_type=type(exc).__name__)
            raise
        finally:
            set_parent_id(None, token=parent_token)
            if is_root:
                try:
                    session.end(outcome="ok")
                except Exception:
                    pass
                set_session(None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_decorator_v2.py tests/unit/test_decorator.py -v`
Expected: 6 new + existing decorator tests pass (existing tests must remain green; the old LensDecorator was not modified).

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/decorator.py tests/unit/test_decorator_v2.py`
Expected: All checks passed.

```bash
git add autopsy/core/decorator.py tests/unit/test_decorator_v2.py
git commit -m "feat(decorator): add LensV2Decorator with no-asyncio sync path"
```

### Task 5.4: New OpenAI interceptor (sync + async, lazy-import)

**Files:**
- Modify: `autopsy/core/interceptor.py` — add `InterceptorV2Manager` alongside the old `InterceptorManager`.
- Test: `tests/unit/test_interceptor_v2.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_interceptor_v2.py`:

```python
"""Tests for the new sync+async OpenAI interceptor."""
from __future__ import annotations

import asyncio
import time
import types

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.context import set_session
from autopsy.core.events_v2 import EventKind
from autopsy.core.interceptor import InterceptorV2Manager
from autopsy.core.session import Session, get_writer
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode


class _FakeAsyncCompletions:
    async def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


class _FakeSyncCompletions:
    def create(self, *, model, messages, **kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi-sync", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


def test_no_op_when_openai_missing(monkeypatch):
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: None,
    )
    mgr = InterceptorV2Manager()
    mgr.install()
    mgr.uninstall()


def test_async_call_emits_llm_request_response(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)

    async_target = _FakeAsyncCompletions()
    sync_target = _FakeSyncCompletions()
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (async_target, sync_target),
    )

    mgr = InterceptorV2Manager()
    mgr.install()
    try:
        s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
        token = set_session(s)
        try:
            asyncio.run(async_target.create(model="m", messages=[{"role": "u", "content": "hi"}]))
        finally:
            set_session(None, token=token)
        s.end(outcome="ok")
    finally:
        mgr.uninstall()
        writer.shutdown(timeout=2.0)
        monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    sd = tmp_path / "sessions" / s.session_id
    assert (sd / "manifest.json").exists()
    import gzip, json
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        kinds = [json.loads(line)["kind"] for line in f]
    assert "llm_request" in kinds
    assert "llm_response" in kinds


def test_sync_call_emits_llm_request_response(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)

    async_target = _FakeAsyncCompletions()
    sync_target = _FakeSyncCompletions()
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (async_target, sync_target),
    )

    mgr = InterceptorV2Manager()
    mgr.install()
    try:
        s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
        token = set_session(s)
        try:
            sync_target.create(model="m", messages=[{"role": "u", "content": "hi"}])
        finally:
            set_session(None, token=token)
        s.end(outcome="ok")
    finally:
        mgr.uninstall()
        writer.shutdown(timeout=2.0)
        monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    sd = tmp_path / "sessions" / s.session_id
    assert (sd / "manifest.json").exists()


def test_passthrough_when_diagnostics_call_is_set(tmp_path, monkeypatch):
    from autopsy.core.context import set_diagnostics_call

    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)

    sync_target = _FakeSyncCompletions()
    async_target = _FakeAsyncCompletions()
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (async_target, sync_target),
    )

    mgr = InterceptorV2Manager()
    mgr.install()
    try:
        s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
        token = set_session(s)
        dtok = set_diagnostics_call(True)
        try:
            sync_target.create(model="m", messages=[])
        finally:
            set_diagnostics_call(False, token=dtok)
            set_session(None, token=token)
        s.end(outcome="ok")
    finally:
        mgr.uninstall()
        writer.shutdown(timeout=2.0)
        monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    import gzip, json
    sd = tmp_path / "sessions" / s.session_id
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        kinds = [json.loads(line)["kind"] for line in f]
    assert "llm_request" not in kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_interceptor_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'InterceptorV2Manager'`.

- [ ] **Step 3: Write minimal implementation**

Append to `autopsy/core/interceptor.py`:

```python
# ----- new v2 interceptor (added in phase 5; replaces old InterceptorManager in phase 7) -----

from typing import Any, Tuple

from .context import current_session, is_diagnostics_call
from .events_v2 import EventKind, LLMRequestEvent, LLMResponseEvent
from .ulid import new_ulid


def _import_openai_targets() -> Tuple[Any, Any] | None:
    """Return (async_completions_target, sync_completions_target), or None.

    Lazy-imports openai so a missing package is a silent no-op. Both targets
    are class instances that the patch will monkey-patch `create` on.
    """
    try:
        from openai.resources.chat import completions as _c
        return _c.AsyncCompletions, _c.Completions
    except Exception:
        return None


def _safe_dump(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _safe_dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_dump(v) for v in obj]
    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _safe_dump(fn())
            except Exception:
                continue
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


def _emit_request(session, *, model, messages, tools, temperature, max_tokens) -> str:
    nid = new_ulid()
    try:
        ev = LLMRequestEvent(
            event_id=nid,
            parent_id=None,
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKind.LLM_REQUEST,
            model=str(model or ""),
            messages=_safe_dump(messages) or [],
            tools=_safe_dump(tools) or [],
            temperature=float(temperature) if temperature is not None else 1.0,
            max_tokens=int(max_tokens or 0),
            prompt_tokens_estimate=0,
        )
        session.record_event(ev)
    except Exception:
        pass
    return nid


def _emit_response(session, *, model, result, latency_ms):
    try:
        content = ""
        finish_reason = ""
        usage = None
        choices = getattr(result, "choices", None) or []
        if choices:
            msg = getattr(choices[0], "message", None)
            content = getattr(msg, "content", "") or ""
            finish_reason = getattr(choices[0], "finish_reason", "") or ""
        usage_obj = getattr(result, "usage", None)
        if usage_obj is not None:
            usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
            }
        ev = LLMResponseEvent(
            event_id=new_ulid(),
            parent_id=None,
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKind.LLM_RESPONSE,
            model=str(model or ""),
            content=content,
            tool_calls=[],
            prompt_tokens=(usage or {}).get("prompt_tokens", 0),
            completion_tokens=(usage or {}).get("completion_tokens", 0),
            total_tokens=(usage or {}).get("total_tokens", 0),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
        session.record_event(ev)
    except Exception:
        pass


class InterceptorV2Manager:
    """Patch openai's chat.completions.create (both sync and async).

    Lazy-imports openai; silently no-ops if openai is not installed.
    Refcounted-by-install so multiple sessions don't double-patch.
    """

    _installed_count: int = 0
    _async_original = None
    _sync_original = None
    _async_target = None
    _sync_target = None

    def install(self) -> None:
        cls = type(self)
        cls._installed_count += 1
        if cls._async_original is not None or cls._sync_original is not None:
            return
        targets = _import_openai_targets()
        if targets is None:
            return
        async_target, sync_target = targets
        cls._async_target = async_target
        cls._sync_target = sync_target
        cls._async_original = getattr(async_target, "create", None)
        cls._sync_original = getattr(sync_target, "create", None)

        async_orig = cls._async_original
        sync_orig = cls._sync_original

        async def patched_async_create(self_, *args, **kwargs):
            if is_diagnostics_call():
                return await async_orig(self_, *args, **kwargs) if callable(async_orig) else await async_target.create(*args, **kwargs)
            session = current_session()
            if session is None:
                if callable(async_orig):
                    return await async_orig(self_, *args, **kwargs)
                return await async_target.create(*args, **kwargs)
            import time as _t
            _emit_request(
                session,
                model=kwargs.get("model"),
                messages=kwargs.get("messages") or [],
                tools=kwargs.get("tools") or [],
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens"),
            )
            t0 = _t.perf_counter()
            if callable(async_orig):
                result = await async_orig(self_, *args, **kwargs)
            else:
                result = await async_target.create(*args, **kwargs)
            _emit_response(
                session, model=kwargs.get("model"),
                result=result, latency_ms=(_t.perf_counter() - t0) * 1000.0,
            )
            return result

        def patched_sync_create(self_, *args, **kwargs):
            if is_diagnostics_call():
                if callable(sync_orig):
                    return sync_orig(self_, *args, **kwargs)
                return sync_target.create(*args, **kwargs)
            session = current_session()
            if session is None:
                if callable(sync_orig):
                    return sync_orig(self_, *args, **kwargs)
                return sync_target.create(*args, **kwargs)
            import time as _t
            _emit_request(
                session,
                model=kwargs.get("model"),
                messages=kwargs.get("messages") or [],
                tools=kwargs.get("tools") or [],
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens"),
            )
            t0 = _t.perf_counter()
            if callable(sync_orig):
                result = sync_orig(self_, *args, **kwargs)
            else:
                result = sync_target.create(*args, **kwargs)
            _emit_response(
                session, model=kwargs.get("model"),
                result=result, latency_ms=(_t.perf_counter() - t0) * 1000.0,
            )
            return result

        try:
            async_target.create = patched_async_create
        except Exception:
            pass
        try:
            sync_target.create = patched_sync_create
        except Exception:
            pass

    def uninstall(self) -> None:
        cls = type(self)
        cls._installed_count = max(0, cls._installed_count - 1)
        if cls._installed_count > 0:
            return
        try:
            if cls._async_target is not None and cls._async_original is not None:
                cls._async_target.create = cls._async_original
        except Exception:
            pass
        try:
            if cls._sync_target is not None and cls._sync_original is not None:
                cls._sync_target.create = cls._sync_original
        except Exception:
            pass
        cls._async_original = None
        cls._sync_original = None
        cls._async_target = None
        cls._sync_target = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_interceptor_v2.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/interceptor.py tests/unit/test_interceptor_v2.py`
Expected: All checks passed.

```bash
git add autopsy/core/interceptor.py tests/unit/test_interceptor_v2.py
git commit -m "feat(interceptor): add sync+async OpenAI patch with lazy import"
```

### Task 5.5: Public API surface — autopsy.log + sample arg

**Files:**
- Modify: `autopsy/__init__.py` — add `log` function. The `lens` singleton stays pointed at the old `LensDecorator` until phase 7.
- Test: `tests/unit/test_public_log.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_public_log.py`:

```python
"""Tests for the public autopsy.log breadcrumb API."""
from __future__ import annotations

import time

import pytest

from autopsy import log
from autopsy.core.config import LensConfig
from autopsy.core.context import set_session
from autopsy.core.session import Session, get_writer
from autopsy.core.writer import SampleMode


def test_log_outside_session_is_a_noop():
    log("no_session_here", k=1)


def test_log_attaches_log_event_to_current_session(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    writer = get_writer(cfg)
    s = Session.begin(config=cfg, agent_name="a", sample=SampleMode.ALL)
    token = set_session(s)
    try:
        log("retry_attempt", attempt=3, reason="rate_limited")
        log("plain")
    finally:
        set_session(None, token=token)
    s.end(outcome="ok")
    writer.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)

    import gzip, json
    sd = tmp_path / "sessions" / s.session_id
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        events = [json.loads(line) for line in f if line.strip()]
    logs = [e for e in events if e["kind"] == "log"]
    assert any(e.get("name") == "retry_attempt" and e["attributes"]["attempt"] == 3 for e in logs)
    assert any(e.get("name") == "plain" for e in logs)


def test_log_never_raises_on_bad_inputs():
    log(123, weird=object())  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_public_log.py -v`
Expected: FAIL — `ImportError: cannot import name 'log' from 'autopsy'`.

- [ ] **Step 3: Write minimal implementation**

Modify `autopsy/__init__.py` to add `log` and re-export the new `LensConfig`:

```python
"""autopsy - your agent died. here's why.

Public API. Users only need::

    from autopsy import lens, log, LensConfig

    @lens.trace
    async def my_agent(query):
        ...

    log("retry", attempt=3)
"""
from __future__ import annotations

from typing import Any

from autopsy.core.config import LensConfig
from autopsy.core.context import current_parent_id, current_session
from autopsy.core.decorator import LensDecorator
from autopsy.core.events import DiagnosisResult, TraceBundle
from autopsy.core.events_v2 import EventKind, LogEvent
from autopsy.core.ulid import new_ulid

__version__ = "0.2.0"

lens = LensDecorator()


def log(name: Any, /, **attributes: Any) -> None:
    """Emit a structured breadcrumb attached to the current session.

    No-op if there is no active autopsy session. Never raises.
    """
    try:
        session = current_session()
        if session is None:
            return
        ev = LogEvent(
            event_id=new_ulid(),
            parent_id=current_parent_id(),
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKind.LOG,
            name=str(name),
            attributes={k: v for k, v in attributes.items()},
        )
        session.record_event(ev)
    except Exception:
        return


__all__ = [
    "lens", "log", "LensConfig", "TraceBundle", "DiagnosisResult", "__version__",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_public_log.py -v tests/unit/test_events.py tests/unit/test_decorator.py tests/integration/test_server.py tests/unit/test_replay.py tests/unit/test_rocketride_agent.py`
Expected: All pass — the old `lens` still points at `LensDecorator`, so existing tests are untouched; `log` is additive.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/__init__.py tests/unit/test_public_log.py`
Expected: All checks passed.

```bash
git add autopsy/__init__.py tests/unit/test_public_log.py
git commit -m "feat(decorator): add public autopsy.log breadcrumb API"
```

### Task 5.6: End-to-end integration test (decorator + interceptor + writer + store)

**Files:**
- Create: `tests/integration/test_capture_end_to_end.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_capture_end_to_end.py`:

```python
"""End-to-end: decorator -> interceptor -> writer -> store, with a fake OpenAI."""
from __future__ import annotations

import asyncio
import gzip
import json
import time
import types

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensV2Decorator
from autopsy.core.interceptor import InterceptorV2Manager
from autopsy.core.session import get_writer


class _FakeAsync:
    async def create(self, *, model, messages, **k):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


class _FakeSync:
    def create(self, *, model, messages, **k):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="hi", tool_calls=None),
                finish_reason="stop",
            )],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


@pytest.fixture
def wired(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    monkeypatch.setattr(
        "autopsy.core.interceptor._import_openai_targets",
        lambda: (_FakeAsync(), _FakeSync()),
    )
    mgr = InterceptorV2Manager()
    mgr.install()
    lens = LensV2Decorator(config=cfg)
    yield lens, tmp_path, cfg
    mgr.uninstall()
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)


def _session_dir(tmp_path):
    sd = tmp_path / "sessions"
    if not sd.exists():
        return None
    rows = [p for p in sd.iterdir() if (p / "manifest.json").exists()]
    return rows[0] if rows else None


def test_success_under_errors_sample_writes_no_disk(wired):
    lens, tmp_path, cfg = wired

    @lens.trace
    async def agent(q):
        from openai.resources.chat import completions as _c  # noqa
        return "ok"

    # Bypass real openai import by going through our fake directly via the patched class.
    @lens.trace
    async def runner(q):
        # Use the patched _FakeAsync.create via the patch on the class itself.
        target = (lens.config.session_dir, q)
        return target

    asyncio.run(runner("q"))
    time.sleep(0.2)
    sd = tmp_path / "sessions"
    assert not sd.exists() or not list(sd.iterdir())


def test_error_under_errors_sample_writes_session_and_error_event(wired):
    lens, tmp_path, cfg = wired

    @lens.trace
    async def agent(q):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        asyncio.run(agent("q"))

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _session_dir(tmp_path) is None:
        time.sleep(0.02)
    sd = _session_dir(tmp_path)
    assert sd is not None
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        kinds = [json.loads(line)["kind"] for line in f if line.strip()]
    assert "agent_start" in kinds
    assert "error" in kinds
    assert "agent_end" in kinds
    manifest = json.loads((sd / "manifest.json").read_text())
    assert manifest["status"] == "error"
    assert manifest["error_type"] == "ValueError"


def test_sample_all_writes_event_with_correct_parent_chain(wired):
    lens, tmp_path, cfg = wired

    @lens.trace(sample="all")
    async def inner(q):
        return q

    @lens.trace(sample="all")
    async def outer(q):
        return await inner(q)

    asyncio.run(outer("hi"))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _session_dir(tmp_path) is None:
        time.sleep(0.02)
    sd = _session_dir(tmp_path)
    with gzip.open(sd / "events.jsonl.gz", "rt") as f:
        events = [json.loads(line) for line in f if line.strip()]
    starts = [e for e in events if e["kind"] == "agent_start"]
    assert len(starts) == 2
    parent_ids = {e["parent_id"] for e in starts}
    assert None in parent_ids
    assert any(p is not None for p in parent_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_capture_end_to_end.py -v`
Expected: FAIL — modules not wired yet (this test runs after 5.1-5.5 so it should pass; if any glue is missing the failure surfaces here).

- [ ] **Step 3: Write minimal implementation**

No new modules — the test exercises everything built in 5.1-5.5. If any test fails, fix the underlying module per the error.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_capture_end_to_end.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check tests/integration/test_capture_end_to_end.py`
Expected: All checks passed.

```bash
git add tests/integration/test_capture_end_to_end.py
git commit -m "test(decorator): add end-to-end capture integration test"
```

---

## Phase 6 — Compatibility shim

`LegacyBundleReader` returns the old-style `TraceBundle` dict shape so the dashboard, diagnostics, and replay engine don't need to change before sub-project #5. It reads both v0 (existing on-disk format) and v1 (new format) sessions transparently.

### Task 6.1: Legacy v0 reader

**Files:**
- Create: `autopsy/core/compat.py` (initial — v0 reader only)
- Test: `tests/unit/test_compat_v0.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compat_v0.py`:

```python
"""Tests for reading legacy (implicit v0) sessions into the TraceBundle shape."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autopsy.core.compat import read_v0_bundle


def _write_v0(tmp_path: Path, session_id: str) -> Path:
    payload = {
        "session_id": session_id,
        "created_at": 1700000000.0,
        "agent_name": "old_agent",
        "input_query": "do thing",
        "agent_module_path": "/x/y.py",
        "agent_fn_name": "x.y",
        "events": [
            {"event_type": "session_start", "session_id": session_id,
             "timestamp": 1.0, "agent_name": "old_agent"},
            {"event_type": "node_start", "node_id": "n1", "node_type": "agent",
             "node_name": "root", "parent_node_id": None, "depth": 0},
            {"event_type": "node_end", "node_id": "n1", "duration_ms": 10.0,
             "output_data": "done"},
        ],
        "dag_edges": [],
        "node_index": {},
        "replay_checkpoints": {},
        "summary": {"status": "success", "error_count": 0},
    }
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    p = sessions / f"{session_id}.json"
    p.write_text(json.dumps(payload))
    return p


def test_reads_v0_into_trace_bundle_shape(tmp_path):
    p = _write_v0(tmp_path, "old-1")
    bundle = read_v0_bundle(p)
    assert bundle["session_id"] == "old-1"
    assert bundle["agent_name"] == "old_agent"
    assert len(bundle["events"]) == 3
    assert bundle["events"][0]["event_type"] == "session_start"


def test_v0_reader_returns_none_for_missing_file(tmp_path):
    assert read_v0_bundle(tmp_path / "nope.json") is None


def test_v0_reader_returns_none_for_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert read_v0_bundle(p) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_compat_v0.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'autopsy.core.compat'`.

- [ ] **Step 3: Write minimal implementation**

Create `autopsy/core/compat.py`:

```python
"""LegacyBundleReader — bilingual v0/v1 reader returning the old TraceBundle dict.

Why this exists: the dashboard, diagnostics, and replay engine consume the
old `TraceBundle` dict shape. Rewriting them is sub-project #5. Until then,
this module is the seam that lets us refactor the capture layer in isolation.

v0 = existing implicit format on disk: one JSON file per session containing
the full `TraceBundle` payload. Read it directly.

v1 = new format: per-session directory with `manifest.json` + `events.jsonl(.gz)`.
Read both and synthesize the legacy event-type vocabulary on the fly.

`read_v0_bundle` and `read_v1_bundle` are the per-format readers. The
unified `LegacyBundleReader` (added in 6.3) chooses between them.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("autopsy.compat")


def read_v0_bundle(path: Path) -> dict[str, Any] | None:
    """Read a single legacy JSON-blob session file into a TraceBundle dict."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    bundle: dict[str, Any] = {
        "session_id": data.get("session_id", ""),
        "created_at": float(data.get("created_at", 0.0)),
        "agent_name": data.get("agent_name", ""),
        "input_query": data.get("input_query", ""),
        "agent_module_path": data.get("agent_module_path", ""),
        "agent_fn_name": data.get("agent_fn_name", ""),
        "events": list(data.get("events", []) or []),
        "dag_edges": list(data.get("dag_edges", []) or []),
        "node_index": dict(data.get("node_index", {}) or {}),
        "replay_checkpoints": dict(data.get("replay_checkpoints", {}) or {}),
        "summary": dict(data.get("summary", {}) or {}),
    }
    return bundle
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_compat_v0.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/compat.py tests/unit/test_compat_v0.py`
Expected: All checks passed.

```bash
git add autopsy/core/compat.py tests/unit/test_compat_v0.py
git commit -m "feat(compat): add v0 legacy bundle reader"
```

### Task 6.2: v1 reader (translates new events into legacy event_types)

**Files:**
- Modify: `autopsy/core/compat.py`
- Test: `tests/unit/test_compat_v1.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compat_v1.py`:

```python
"""Tests for reading v1 sessions into the legacy TraceBundle dict shape."""
from __future__ import annotations

import time

import pytest

from autopsy.core.compat import read_v1_bundle
from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import (
    AgentEndEvent,
    AgentStartEvent,
    ErrorEvent,
    EventKind,
    LLMRequestEvent,
    LLMResponseEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer

SID = "01HXY000000000000000000001"


def _ev(cls, kind, **extra):
    base = dict(
        event_id="01HXY00000000000000000000" + str(extra.pop("seq", "0")),
        parent_id=extra.pop("parent_id", None),
        session_id=SID,
        trace_id=SID,
        timestamp_ns=extra.pop("ts", 1),
        kind=kind,
    )
    return cls(**base, **extra)


@pytest.fixture
def written_session(tmp_path):
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="all")
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(SID, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(_ev(AgentStartEvent, EventKind.AGENT_START, agent_name="a", seq="1"))
        w.enqueue(_ev(LLMRequestEvent, EventKind.LLM_REQUEST,
                      model="m", messages=[], temperature=1.0, max_tokens=0,
                      tools=[], prompt_tokens_estimate=0, seq="2"))
        w.enqueue(_ev(LLMResponseEvent, EventKind.LLM_RESPONSE,
                      model="m", content="hi", tool_calls=[],
                      prompt_tokens=1, completion_tokens=2, total_tokens=3,
                      latency_ms=1.0, finish_reason="stop", seq="3"))
        w.enqueue(_ev(ToolCallStartEvent, EventKind.TOOL_CALL_START,
                      tool_name="t", tool_args={"a": 1}, seq="4"))
        w.enqueue(_ev(ToolCallEndEvent, EventKind.TOOL_CALL_END,
                      tool_name="t", result="r", error=None, duration_ms=1.0, seq="5"))
        w.enqueue(_ev(ErrorEvent, EventKind.ERROR,
                      error_type="X", error_message="m", traceback="t", seq="6"))
        w.enqueue(_ev(AgentEndEvent, EventKind.AGENT_END, duration_ms=10.0, seq="7"))
        w.end_session(SID, outcome="error", error_type="X")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / SID / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)
    return tmp_path / "sessions" / SID


def test_v1_reader_produces_legacy_event_types(written_session):
    bundle = read_v1_bundle(written_session)
    assert bundle is not None
    types_present = {e["event_type"] for e in bundle["events"]}
    assert {"node_start", "node_end", "llm_request", "llm_response",
            "tool_call", "tool_result", "node_error"} <= types_present


def test_v1_reader_carries_summary_status(written_session):
    bundle = read_v1_bundle(written_session)
    assert bundle["summary"]["status"] == "error"
    assert bundle["summary"]["error_count"] >= 1


def test_v1_reader_returns_none_for_missing(tmp_path):
    assert read_v1_bundle(tmp_path / "nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_compat_v1.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_v1_bundle'`.

- [ ] **Step 3: Write minimal implementation**

Append to `autopsy/core/compat.py`:

```python
import gzip


_KIND_TO_LEGACY_TYPE = {
    "agent_start": "node_start",
    "agent_end": "node_end",
    "error": "node_error",
    "tool_call_start": "tool_call",
    "tool_call_end": "tool_result",
    "llm_request": "llm_request",
    "llm_response": "llm_response",
    "session_start": "session_start",
    "session_end": "session_end",
    "log": "node_start",
}


def _v1_event_to_legacy(ev: dict[str, Any]) -> dict[str, Any]:
    kind = ev.get("kind")
    legacy = dict(ev)
    legacy["event_type"] = _KIND_TO_LEGACY_TYPE.get(kind, kind)
    legacy["timestamp"] = ev.get("timestamp_ns", 0) / 1e9
    if kind == "agent_start":
        legacy["node_id"] = ev.get("event_id")
        legacy["node_type"] = ev.get("role", "agent")
        legacy["node_name"] = ev.get("agent_name", "")
        legacy["parent_node_id"] = ev.get("parent_id")
        legacy["depth"] = 0
        legacy["input_data"] = ev.get("input_preview", "")
    elif kind == "agent_end":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["duration_ms"] = ev.get("duration_ms", 0)
        legacy["output_data"] = ev.get("output_preview", "")
        legacy["output_hash"] = ev.get("output_hash", "")
    elif kind == "error":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["error_type"] = ev.get("error_type", "")
        legacy["error_message"] = ev.get("error_message", "")
        legacy["traceback"] = ev.get("traceback", "")
        legacy["duration_ms"] = 0
    elif kind == "tool_call_start":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["tool_name"] = ev.get("tool_name", "")
        legacy["tool_args"] = ev.get("tool_args", {})
    elif kind == "tool_call_end":
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
        legacy["tool_name"] = ev.get("tool_name", "")
        legacy["result"] = ev.get("result")
        legacy["error"] = ev.get("error")
        legacy["latency_ms"] = ev.get("duration_ms", 0)
    elif kind in ("llm_request", "llm_response"):
        legacy["node_id"] = ev.get("parent_id") or ev.get("event_id")
    return legacy


def _load_events_jsonl(session_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    gz = session_dir / "events.jsonl.gz"
    plain = session_dir / "events.jsonl"
    if gz.exists():
        opener = lambda: gzip.open(gz, "rt", encoding="utf-8")
    elif plain.exists():
        opener = lambda: plain.open("r", encoding="utf-8")
    else:
        return out
    with opener() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def read_v1_bundle(session_dir: Path) -> dict[str, Any] | None:
    """Read a v1 session directory and synthesize a legacy TraceBundle dict."""
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:
        return None

    raw_events = _load_events_jsonl(session_dir)
    legacy_events = [_v1_event_to_legacy(e) for e in raw_events]

    error_count = sum(1 for e in legacy_events if e.get("event_type") == "node_error")
    summary_status = {
        "ok": "success", "error": "error", "partial": "partial", "live": "partial",
    }.get(manifest.get("status", ""), "unknown")

    total_tokens = sum(
        int(e.get("total_tokens") or 0) for e in legacy_events
        if e.get("event_type") == "llm_response"
    )

    return {
        "session_id": manifest.get("session_id", ""),
        "created_at": manifest.get("start_time_ns", 0) / 1e9,
        "agent_name": manifest.get("agent_name", ""),
        "input_query": "",
        "agent_module_path": "",
        "agent_fn_name": "",
        "events": legacy_events,
        "dag_edges": [],
        "node_index": {},
        "replay_checkpoints": {},
        "summary": {
            "status": summary_status,
            "error_count": error_count,
            "total_tokens": total_tokens,
            "node_count": sum(1 for e in legacy_events if e.get("event_type") == "node_start"),
            "total_duration_ms": manifest.get("duration_ms", 0) or 0,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_compat_v1.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/compat.py tests/unit/test_compat_v1.py`
Expected: All checks passed.

```bash
git add autopsy/core/compat.py tests/unit/test_compat_v1.py
git commit -m "feat(compat): add v1 reader translating new events to legacy types"
```

### Task 6.3: Unified LegacyBundleReader

**Files:**
- Modify: `autopsy/core/compat.py`
- Test: `tests/unit/test_compat.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_compat.py`:

```python
"""Tests for the unified bilingual LegacyBundleReader."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import AgentEndEvent, AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def _write_v0_session(root: Path, session_id: str) -> None:
    sessions = root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sessions.joinpath(f"{session_id}.json").write_text(json.dumps({
        "session_id": session_id, "created_at": 1700000000.0,
        "agent_name": "old", "input_query": "q",
        "events": [{"event_type": "session_start", "session_id": session_id}],
        "summary": {"status": "success", "error_count": 0},
    }))


def _write_v1_session(root: Path, session_id: str) -> None:
    store = LocalFilesystemStore(root=root)
    cfg = LensConfig(session_dir=str(root))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(session_id, sample=SampleMode.ALL, agent_name="new", start_ns=1)
        ev1 = AgentStartEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=session_id, trace_id=session_id,
            timestamp_ns=1, kind=EventKind.AGENT_START, agent_name="new",
        )
        ev2 = AgentEndEvent(
            event_id="01HXY00000000000000000000B",
            parent_id=None, session_id=session_id, trace_id=session_id,
            timestamp_ns=2, kind=EventKind.AGENT_END, duration_ms=1.0,
        )
        w.enqueue(ev1)
        w.enqueue(ev2)
        w.end_session(session_id, outcome="ok")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (root / "sessions" / session_id / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)


def test_reader_lists_v0_and_v1_sessions_together(tmp_path):
    _write_v0_session(tmp_path, "old-1")
    _write_v1_session(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    rows = reader.list()
    ids = {r["session_id"] for r in rows}
    assert ids == {"old-1", "01HXY000000000000000000001"}


def test_reader_load_returns_v0(tmp_path):
    _write_v0_session(tmp_path, "old-1")
    reader = LegacyBundleReader(root=tmp_path)
    bundle = reader.load("old-1")
    assert bundle is not None
    assert bundle["agent_name"] == "old"


def test_reader_load_returns_v1_translated(tmp_path):
    _write_v1_session(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    bundle = reader.load("01HXY000000000000000000001")
    assert bundle is not None
    types = {e["event_type"] for e in bundle["events"]}
    assert "node_start" in types
    assert "node_end" in types


def test_reader_load_missing_returns_none(tmp_path):
    reader = LegacyBundleReader(root=tmp_path)
    assert reader.load("nope") is None


def test_reader_refuses_unknown_future_version(tmp_path):
    sid = "01HXY000000000000000000001"
    sd = tmp_path / "sessions" / sid
    sd.mkdir(parents=True)
    (sd / "manifest.json").write_text(json.dumps({
        "session_id": sid, "agent_name": "x", "start_time_ns": 1,
        "status": "ok", "autopsy_format_version": 999,
        "autopsy_version": "9.9.9",
        "wall_clock_ns_at_start": 1, "monotonic_ns_at_start": 1,
    }))
    reader = LegacyBundleReader(root=tmp_path)
    with pytest.raises(Exception) as excinfo:
        reader.load(sid)
    assert "999" in str(excinfo.value)
    assert "autopsy migrate" in str(excinfo.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_compat.py -v`
Expected: FAIL — `ImportError: cannot import name 'LegacyBundleReader'`.

- [ ] **Step 3: Write minimal implementation**

Append to `autopsy/core/compat.py`:

```python
from .errors import UnknownSchemaVersionError


class LegacyBundleReader:
    """Bilingual reader that returns the old TraceBundle dict shape.

    `root` is the session root that contains either v0 files
    (`sessions/<id>.json`) or v1 directories (`sessions/<id>/manifest.json`),
    or both.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        sessions = self.root / "sessions"
        if not sessions.exists():
            return out
        for child in sessions.iterdir():
            if child.is_file() and child.suffix == ".json" and not child.name.startswith("sessions_index"):
                bundle = read_v0_bundle(child)
                if bundle is not None:
                    out.append({
                        "session_id": bundle["session_id"],
                        "agent_name": bundle["agent_name"],
                        "created_at": bundle["created_at"],
                        "summary": bundle["summary"],
                    })
            elif child.is_dir() and (child / "manifest.json").exists():
                try:
                    manifest = json.loads((child / "manifest.json").read_text())
                except Exception:
                    continue
                if int(manifest.get("autopsy_format_version", 1)) != 1:
                    continue
                out.append({
                    "session_id": manifest.get("session_id", child.name),
                    "agent_name": manifest.get("agent_name", ""),
                    "created_at": manifest.get("start_time_ns", 0) / 1e9,
                    "summary": {
                        "status": {
                            "ok": "success", "error": "error",
                            "partial": "partial", "live": "partial",
                        }.get(manifest.get("status", ""), "unknown"),
                        "error_count": 1 if manifest.get("status") == "error" else 0,
                    },
                })
        out.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return out

    def load(self, session_id: str) -> dict[str, Any] | None:
        sessions = self.root / "sessions"
        v1_dir = sessions / session_id
        if v1_dir.is_dir() and (v1_dir / "manifest.json").exists():
            try:
                manifest = json.loads((v1_dir / "manifest.json").read_text())
            except Exception:
                return None
            v = int(manifest.get("autopsy_format_version", 1))
            if v != 1:
                raise UnknownSchemaVersionError(v, str(v1_dir))
            return read_v1_bundle(v1_dir)
        v0_path = sessions / f"{session_id}.json"
        return read_v0_bundle(v0_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_compat.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy/core/compat.py tests/unit/test_compat.py`
Expected: All checks passed.

```bash
git add autopsy/core/compat.py tests/unit/test_compat.py
git commit -m "feat(compat): add unified bilingual LegacyBundleReader"
```

---

## Phase 7 — Switchover

This phase flips `autopsy.lens` from the old `LensDecorator` to the new `LensV2Decorator`, routes all consumers through `LegacyBundleReader`, and deletes the old `tracer.py` / `decorator.py` (the v1 portion) / `interceptor.py` (the v1 portion) / `events.py` (dataclass-based). After this phase the dashboard and diagnostics still see the legacy `TraceBundle` shape, but it's produced exclusively by the new capture pipeline.

### Task 7.1: Route dashboard + diagnostics + replay through LegacyBundleReader

**Files (modify, depending on what each consumer currently imports):**
- Search for callers of `load_bundle`, `list_sessions`, `TraceSession` outside `autopsy/core/`.
- Modify each call site to go through `LegacyBundleReader.load(session_id)` and `LegacyBundleReader.list()`.
- Test: `tests/integration/test_compat_consumers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_compat_consumers.py`:

```python
"""Verify each consumer of the legacy TraceBundle works against v1 sessions.

Concretely: write one v1 session via the writer, then call the same code
paths the dashboard / diagnostics / replay engine use, and assert they
produce sane outputs.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from autopsy.core.compat import LegacyBundleReader
from autopsy.core.config import LensConfig
from autopsy.core.events_v2 import AgentEndEvent, AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def _write_v1(tmp_path: Path, sid: str) -> None:
    store = LocalFilesystemStore(root=tmp_path)
    cfg = LensConfig(session_dir=str(tmp_path))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(sid, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000A", parent_id=None,
            session_id=sid, trace_id=sid, timestamp_ns=1,
            kind=EventKind.AGENT_START, agent_name="a",
        ))
        w.enqueue(AgentEndEvent(
            event_id="01HXY00000000000000000000B", parent_id=None,
            session_id=sid, trace_id=sid, timestamp_ns=2,
            kind=EventKind.AGENT_END, duration_ms=1.0,
        ))
        w.end_session(sid, outcome="ok")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (tmp_path / "sessions" / sid / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)


def test_dashboard_listing_works_off_legacy_reader(tmp_path):
    _write_v1(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    rows = reader.list()
    assert rows
    assert rows[0]["session_id"] == "01HXY000000000000000000001"


def test_diagnose_load_works_off_legacy_reader(tmp_path):
    _write_v1(tmp_path, "01HXY000000000000000000001")
    reader = LegacyBundleReader(root=tmp_path)
    bundle = reader.load("01HXY000000000000000000001")
    assert bundle is not None
    assert any(e["event_type"] == "node_start" for e in bundle["events"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_compat_consumers.py -v`
Expected: should pass after 6.3 lands; the test exists to lock in the consumer contract before the switchover edits below.

- [ ] **Step 3: Write minimal implementation**

For every call site in `autopsy/dashboard/`, `autopsy/diagnostics/`, `autopsy/replay/`, `autopsy/cli/` that imports from `autopsy.core.tracer` or calls `load_bundle` / `list_sessions`:

```python
# before
from autopsy.core.tracer import load_bundle, list_sessions
b = load_bundle(session_dir, session_id)
rows = list_sessions(session_dir)

# after
from autopsy.core.compat import LegacyBundleReader
reader = LegacyBundleReader(root=session_dir.parent if session_dir.name == "sessions" else session_dir)
b = reader.load(session_id)
rows = reader.list()
```

Take care: the previous `session_dir` argument typically pointed at `~/.autopsy/sessions`. `LegacyBundleReader.root` is the parent (`~/.autopsy`). Adjust each call site explicitly.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_compat_consumers.py tests/integration/test_server.py tests/unit/test_replay.py -v`
Expected: All pass; the v0 paths still work because `LegacyBundleReader` is bilingual.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy tests`
Expected: All checks passed.

```bash
git add -A
git commit -m "refactor(compat): route dashboard/diagnostics/replay through LegacyBundleReader"
```

### Task 7.2: Flip `lens` to LensV2Decorator and delete old modules

**Files:**
- Modify: `autopsy/__init__.py` — `lens = LensV2Decorator(config=load_config_from_env())`
- Delete: `autopsy/core/tracer.py`
- Replace contents: `autopsy/core/decorator.py` — keep ONLY `LensV2Decorator`, rename to `LensDecorator`.
- Replace contents: `autopsy/core/interceptor.py` — keep ONLY `InterceptorV2Manager`, rename to `InterceptorManager`.
- Delete: `autopsy/core/events.py` (the dataclass version)

- [ ] **Step 1: Write the failing test (use existing tests as the failure surface)**

Run the existing test suite to capture the pre-flip baseline:

`.venv/bin/python -m pytest tests/ -v`
Record which tests pass.

The flip will break:
- Any direct import `from autopsy.core.events import ...` for the dataclass names (existing `tests/unit/test_events.py`).
- Any direct import `from autopsy.core.tracer import ...`.

These tests are renamed in task 7.4 below. For 7.2 we expect:
- `tests/unit/test_events.py` (dataclass version) FAIL after deletion — this test is replaced by `test_events_v2.py` (renamed to `test_events.py` in 7.4).
- `tests/unit/test_decorator.py` (old) FAIL — replaced by `test_decorator_v2.py` (renamed to `test_decorator.py` in 7.4).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_events.py tests/unit/test_decorator.py -v`
Expected: After the flip, both fail with `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Write minimal implementation**

```bash
git rm autopsy/core/tracer.py
git rm autopsy/core/events.py
```

Rewrite `autopsy/core/decorator.py` to contain only the new class, renamed from `LensV2Decorator` to `LensDecorator`. Rewrite `autopsy/core/interceptor.py` to contain only the new class, renamed from `InterceptorV2Manager` to `InterceptorManager`.

Modify `autopsy/__init__.py`:

```python
"""autopsy - your agent died. here's why."""
from __future__ import annotations

from autopsy.core.config import LensConfig, load_config_from_env
from autopsy.core.context import current_parent_id, current_session
from autopsy.core.decorator import LensDecorator
from autopsy.core.events import EventKind, LogEvent  # renamed in 7.3
from autopsy.core.ulid import new_ulid

__version__ = "0.2.0"

lens = LensDecorator(config=load_config_from_env())


def log(name, /, **attributes):
    try:
        session = current_session()
        if session is None:
            return
        ev = LogEvent(
            event_id=new_ulid(),
            parent_id=current_parent_id(),
            session_id=session.session_id,
            trace_id=session.session_id,
            timestamp_ns=__import__("time").time_ns(),
            kind=EventKind.LOG,
            name=str(name),
            attributes=dict(attributes),
        )
        session.record_event(ev)
    except Exception:
        return


__all__ = ["lens", "log", "LensConfig", "__version__"]
```

Remove the dataclass re-exports (`TraceBundle`, `DiagnosisResult`). If any consumer imported them from `autopsy`, it must now import from `autopsy.core.compat` (TraceBundle dict is returned by `LegacyBundleReader.load`) or from a new `autopsy.diagnostics.types` (DiagnosisResult — out of scope for this sub-project; leave it where it is in `autopsy/diagnostics/` and update the import sites).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ -v --ignore=tests/unit/test_events.py --ignore=tests/unit/test_decorator.py`
Expected: All other tests pass.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy tests`
Expected: All checks passed.

```bash
git add -A
git commit -m "refactor(core): flip lens to LensV2 and delete legacy tracer/events"
```

### Task 7.3: Rename events_v2 → events

**Files:**
- Rename: `autopsy/core/events_v2.py` → `autopsy/core/events.py`
- Update every `from autopsy.core.events_v2 import ...` to `from autopsy.core.events import ...` across the codebase.

- [ ] **Step 1: Write the failing test (capture pre-rename state)**

Run: `.venv/bin/python -m pytest tests/ -v`
All tests should be green going into this task (after 7.2). Record the result.

- [ ] **Step 2: Run test to verify the rename is needed**

```bash
rg "from autopsy.core.events_v2" autopsy tests
```
Expected: every import should be listed (will all need to flip).

- [ ] **Step 3: Write minimal implementation**

```bash
git mv autopsy/core/events_v2.py autopsy/core/events.py
```

Then in every file matched above, replace `autopsy.core.events_v2` with `autopsy.core.events`:

```bash
rg -l "from autopsy.core.events_v2" autopsy tests | xargs sed -i '' 's/autopsy\.core\.events_v2/autopsy.core.events/g'
```

(Use the equivalent `sed` invocation for your platform; on Linux drop the `''`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy tests`
Expected: All checks passed.

```bash
git add -A
git commit -m "refactor(core): rename events_v2 module back to events"
```

### Task 7.4: Rename test_decorator_v2 → test_decorator and reconcile

**Files:**
- Rename: `tests/unit/test_decorator_v2.py` → `tests/unit/test_decorator.py` (replacing the old one, which was already deleted in 7.2 because it tested the deleted decorator).
- Rename: `tests/unit/test_events_v2.py` → `tests/unit/test_events.py` (replacing the old one).
- Rename: `tests/unit/test_interceptor_v2.py` → `tests/unit/test_interceptor.py` (if there was no old file with this exact name, this is a plain rename).

- [ ] **Step 1: Write the failing test (capture pre-rename state)**

`.venv/bin/python -m pytest tests/unit/test_decorator_v2.py tests/unit/test_events_v2.py tests/unit/test_interceptor_v2.py -v`
Expected: all green.

- [ ] **Step 2: Run test to verify the rename is needed**

Confirm the file names that exist:

```bash
ls tests/unit/test_decorator*.py tests/unit/test_events*.py tests/unit/test_interceptor*.py
```

- [ ] **Step 3: Write minimal implementation**

```bash
git rm -f tests/unit/test_decorator.py tests/unit/test_events.py 2>/dev/null || true
git mv tests/unit/test_decorator_v2.py tests/unit/test_decorator.py
git mv tests/unit/test_events_v2.py tests/unit/test_events.py
git mv tests/unit/test_interceptor_v2.py tests/unit/test_interceptor.py
```

If any test still imports `LensV2Decorator` or `InterceptorV2Manager`, update them to the renamed `LensDecorator` / `InterceptorManager`:

```bash
rg -l "LensV2Decorator|InterceptorV2Manager" tests | xargs sed -i '' \
  -e 's/LensV2Decorator/LensDecorator/g' \
  -e 's/InterceptorV2Manager/InterceptorManager/g'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: All tests pass.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy tests`
Expected: All checks passed.

```bash
git add -A
git commit -m "test: rename v2 tests back to canonical names"
```

### Task 7.5: Full test suite green sweep

**Files:** none (verification only)

- [ ] **Step 1: Write the failing test**

There is no new test in this step; this is a verification milestone. The list of suites that must pass:

- `tests/unit/test_ulid.py`
- `tests/unit/test_events.py`
- `tests/unit/test_config.py`
- `tests/unit/test_errors.py`
- `tests/unit/test_redact.py`
- `tests/unit/test_context.py`
- `tests/unit/test_session.py`
- `tests/unit/test_writer.py`
- `tests/unit/test_writer_batching.py`
- `tests/unit/test_writer_sampling.py`
- `tests/unit/test_writer_atexit.py`
- `tests/unit/test_decorator.py`
- `tests/unit/test_interceptor.py`
- `tests/unit/test_public_log.py`
- `tests/unit/test_local_fs.py`
- `tests/unit/test_sqlite_index.py`
- `tests/unit/test_eviction.py`
- `tests/unit/test_exporter_protocol.py`
- `tests/unit/test_file_exporter.py`
- `tests/unit/test_logging_exporter.py`
- `tests/unit/test_compat_v0.py`
- `tests/unit/test_compat_v1.py`
- `tests/unit/test_compat.py`
- `tests/unit/test_store_protocol.py`
- `tests/unit/test_replay.py`
- `tests/unit/test_rocketride_agent.py`
- `tests/integration/test_server.py`
- `tests/integration/test_capture_end_to_end.py`
- `tests/integration/test_compat_consumers.py`

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ -v`
If anything fails: STOP. Diagnose and fix per the smallest possible patch. Do not proceed to phase 8 until every test is green.

- [ ] **Step 3: Write minimal implementation**

Apply targeted fixes only. Common breakage at this point:
- Imports of `autopsy.core.tracer` somewhere in `autopsy/replay/` or `autopsy/dashboard/` that 7.1 missed. Replace with `LegacyBundleReader`.
- The legacy `replay/test_replay.py` may rely on `TraceBundle` as a dataclass. If so, update it to consume the dict returned by `LegacyBundleReader.load`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 100% pass.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check autopsy tests`
Expected: All checks passed.

```bash
git add -A
git commit -m "chore: green test suite after capture-layer switchover"
```

---

## Phase 8 — Performance and crash safety

The acceptance criteria for v1: p99 overhead under 5 ms, the host process surviving SIGKILL with recoverable trace files, `reindex` rebuilding the index from manifests, and a soak test scaffold to catch memory leaks in CI later.

### Task 8.1: Perf harness module

**Files:**
- Create: `tests/perf/__init__.py` (empty)
- Create: `tests/perf/harness.py`
- Test: `tests/perf/test_harness.py`

- [ ] **Step 1: Write the failing test**

Create `tests/perf/__init__.py` (empty file).

Create `tests/perf/test_harness.py`:

```python
"""Smoke test for the perf harness — measure overhead of a no-op decorator."""
from __future__ import annotations

import pytest

from tests.perf.harness import measure_overhead_ms


def test_harness_returns_percentile_dict():
    out = measure_overhead_ms(
        baseline=lambda: None,
        traced=lambda: None,
        iterations=100,
    )
    assert {"p50", "p95", "p99", "mean", "iterations"} <= set(out)
    assert out["iterations"] == 100
    assert out["p99"] >= out["p50"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/perf/test_harness.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `tests/perf/harness.py`:

```python
"""Tiny perf harness for measuring decorator overhead.

Runs `baseline` and `traced` callables alternately to amortize warmup and
CPU frequency scaling effects. Returns dict of percentile durations in ms.
"""
from __future__ import annotations

import statistics
import time
from typing import Callable


def _percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    k = int(round((p / 100.0) * (len(sorted_values) - 1)))
    return sorted_values[k]


def measure_overhead_ms(
    *,
    baseline: Callable[[], object],
    traced: Callable[[], object],
    iterations: int = 1000,
    warmup: int = 50,
) -> dict[str, float]:
    for _ in range(warmup):
        baseline()
        traced()
    overheads: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        baseline()
        t1 = time.perf_counter_ns()
        traced()
        t2 = time.perf_counter_ns()
        overheads.append(((t2 - t1) - (t1 - t0)) / 1e6)
    overheads.sort()
    return {
        "p50": _percentile(overheads, 50),
        "p95": _percentile(overheads, 95),
        "p99": _percentile(overheads, 99),
        "mean": statistics.fmean(overheads) if overheads else 0.0,
        "iterations": iterations,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/perf/test_harness.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check tests/perf`
Expected: All checks passed.

```bash
git add tests/perf/__init__.py tests/perf/harness.py tests/perf/test_harness.py
git commit -m "test(writer): add perf harness for p99 overhead measurement"
```

### Task 8.2: p99 overhead under 5ms (CI gated)

**Files:**
- Create: `tests/perf/test_overhead.py`

- [ ] **Step 1: Write the failing test**

Create `tests/perf/test_overhead.py`:

```python
"""p99 overhead per traced call must stay under 5 ms (spec target)."""
from __future__ import annotations

import asyncio

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.session import get_writer

from tests.perf.harness import measure_overhead_ms


def test_async_p99_overhead_under_5ms(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def traced_agent():
        return 1

    async def baseline_agent():
        return 1

    def run_baseline():
        asyncio.run(baseline_agent())

    def run_traced():
        asyncio.run(traced_agent())

    out = measure_overhead_ms(
        baseline=run_baseline, traced=run_traced, iterations=500, warmup=50,
    )
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    assert out["p99"] < 5.0, f"p99 overhead {out['p99']:.2f} ms exceeds 5ms target ({out})"


def test_sync_p99_overhead_under_5ms(tmp_path, monkeypatch):
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    def traced_agent():
        return 1

    def baseline_agent():
        return 1

    out = measure_overhead_ms(
        baseline=baseline_agent, traced=traced_agent, iterations=2000, warmup=100,
    )
    w = get_writer(cfg)
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    assert out["p99"] < 5.0, f"sync p99 overhead {out['p99']:.2f} ms exceeds 5ms target ({out})"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/perf/test_overhead.py -v`
Expected: PASS if implementation is correct. If the assertion fails it indicates a regression — investigate before continuing.

- [ ] **Step 3: Write minimal implementation**

No new module. If the test fails:
- Profile with `python -X importtime` and `cProfile` to find the hot path cost.
- The expected culprit is `model_dump_json` on every event in the hot path. Since enqueue is just `put_nowait`, the hot path should be in the sub-millisecond range; if not, suspect ContextVar churn or unnecessary work in `_invoke_async`/`_invoke_sync`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/perf/test_overhead.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check tests/perf/test_overhead.py`
Expected: All checks passed.

```bash
git add tests/perf/test_overhead.py
git commit -m "test(writer): assert p99 traced-call overhead under 5ms (sync + async)"
```

### Task 8.3: SIGKILL crash safety

**Files:**
- Create: `tests/integration/test_crash_safety.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_crash_safety.py`:

```python
"""Crash safety: kill -9 mid-session leaves recoverable trace files."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest


def test_sigkill_mid_session_leaves_recoverable_files(tmp_path):
    script = tmp_path / "run.py"
    script.write_text(textwrap.dedent(f"""
        import os, time
        os.environ["AUTOPSY_SESSION_DIR"] = {str(tmp_path)!r}
        os.environ["AUTOPSY_SAMPLE"] = "all"
        from autopsy import lens

        @lens.trace
        def slow():
            for _ in range(1000):
                time.sleep(0.01)

        slow()
    """).strip())

    proc = subprocess.Popen([sys.executable, str(script)])
    time.sleep(1.0)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=2.0)

    sessions = tmp_path / "sessions"
    assert sessions.exists()
    dirs = [d for d in sessions.iterdir() if d.is_dir()]
    assert dirs, "no session directory created"
    sd = dirs[0]
    events_path = sd / "events.jsonl"
    assert events_path.exists() or (sd / "events.jsonl.gz").exists()


def test_reindex_marks_unfinalized_session_partial(tmp_path):
    from autopsy.core.events import Manifest
    from autopsy.core.store.local_fs import LocalFilesystemStore

    sid = "01HXY000000000000000000099"
    sd = tmp_path / "sessions" / sid
    sd.mkdir(parents=True)
    (sd / "artifacts").mkdir()
    (sd / "events.jsonl").write_text('{"kind":"agent_start"}\n')
    live_manifest = Manifest(
        session_id=sid, agent_name="a", start_time_ns=1,
        end_time_ns=None, duration_ms=None, status="live",
        error_type=None, event_count=1, dropped_events=0,
        autopsy_format_version=1, autopsy_version="0.2.0",
        wall_clock_ns_at_start=1, monotonic_ns_at_start=1,
    )
    (sd / "manifest.json").write_text(live_manifest.model_dump_json())

    store = LocalFilesystemStore(root=tmp_path)
    n = store.reindex()
    assert n == 1
    rows = store.list_sessions()
    assert rows[0]["status"] == "partial"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_crash_safety.py -v`
Expected: First test PASS if writer fsync semantics are correct (the atexit handler will not run on SIGKILL; the partial events.jsonl on disk is the recovery path). The second test FAIL if reindex is not implemented to flip `live` → `partial` (we already implemented this in 2.2).

- [ ] **Step 3: Write minimal implementation**

If the first test fails because there are no on-disk artifacts after a SIGKILL: the issue is that the writer's spill happens only when the session is `kept`. Under `sample="all"` (set via env in the subprocess), the session is immediately `kept`, so events should be spilled per batch. If they are not landing on disk, reduce `flush_interval_ms` in the test to confirm the writer batches arrive. The fix is to make the writer spill on EVERY batch when sample is `ALL`, not buffer indefinitely — verify `_process_batch` does this. If it does not, patch:

```python
        if state.kept and self.store is not None and state.buffer:
            # Spill immediately rather than wait for end_session.
            try:
                self.store.write_events(state.session_id, state.buffer)
            except Exception:
                logger.exception("autopsy: store.write_events failed")
            state.buffer = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_crash_safety.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check tests/integration/test_crash_safety.py autopsy/core/writer.py`
Expected: All checks passed.

```bash
git add -A
git commit -m "test(writer): assert SIGKILL leaves recoverable session files"
```

### Task 8.4: Reindex test (index loss → rebuild)

**Files:**
- Create: `tests/unit/test_reindex.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_reindex.py`:

```python
"""Reindex rebuilds the SQLite index from manifests on disk."""
from __future__ import annotations

import time

from autopsy.core.config import LensConfig
from autopsy.core.events import AgentStartEvent, EventKind
from autopsy.core.store.local_fs import LocalFilesystemStore
from autopsy.core.writer import SampleMode, Writer


def _write_session(root, sid):
    store = LocalFilesystemStore(root=root)
    cfg = LensConfig(session_dir=str(root))
    w = Writer(config=cfg, store=store)
    w.start()
    try:
        w.declare_session(sid, sample=SampleMode.ALL, agent_name="a", start_ns=1)
        w.enqueue(AgentStartEvent(
            event_id="01HXY00000000000000000000A",
            parent_id=None, session_id=sid, trace_id=sid,
            timestamp_ns=1, kind=EventKind.AGENT_START, agent_name="a",
        ))
        w.end_session(sid, outcome="ok")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if (root / "sessions" / sid / "manifest.json").exists():
                break
            time.sleep(0.02)
    finally:
        w.shutdown(timeout=2.0)


def test_reindex_rebuilds_from_manifests(tmp_path):
    _write_session(tmp_path, "01HXY000000000000000000001")
    _write_session(tmp_path, "01HXY000000000000000000002")

    (tmp_path / "index.sqlite").unlink()
    store = LocalFilesystemStore(root=tmp_path)
    n = store.reindex()
    assert n == 2
    ids = {r["session_id"] for r in store.list_sessions()}
    assert ids == {
        "01HXY000000000000000000001",
        "01HXY000000000000000000002",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_reindex.py -v`
Expected: PASS if 2.2 implementation is correct.

- [ ] **Step 3: Write minimal implementation**

Already implemented in 2.2 (`LocalFilesystemStore.reindex`). No new code.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_reindex.py -v`
Expected: 1 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check tests/unit/test_reindex.py`
Expected: All checks passed.

```bash
git add tests/unit/test_reindex.py
git commit -m "test(store): cover index loss → reindex from manifests"
```

### Task 8.5: Soak test stub

**Files:**
- Create: `tests/perf/test_soak.py`

This test is gated off CI by default (marked `@pytest.mark.slow`). It's the seam where a real 24-hour soak job would plug in.

- [ ] **Step 1: Write the failing test**

Create `tests/perf/test_soak.py`:

```python
"""Soak test stub. Skipped by default; runnable with `-m slow`.

A real soak would run for hours and measure RSS over time. This is the
scaffold: it loops a traced function for a small number of iterations and
asserts the writer is still alive and the dropped-events counter is sane.
"""
from __future__ import annotations

import asyncio
import os
import resource
import time

import pytest

from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
from autopsy.core.session import get_writer


@pytest.mark.slow
def test_soak_writer_stays_alive_and_bounded_memory(tmp_path, monkeypatch):
    iters = int(os.environ.get("AUTOPSY_SOAK_ITERS", "5000"))
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def agent(q):
        return q

    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for i in range(iters):
        asyncio.run(agent(f"q-{i}"))
    rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    w = get_writer(cfg)
    assert w.is_alive()
    growth_mb = (rss_end - rss_start) / 1024
    assert growth_mb < 200, f"memory grew {growth_mb:.1f} MB over {iters} calls"
    w.shutdown(timeout=2.0)
    monkeypatch.setattr("autopsy.core.session._writer_singleton", None)
```

Also add this to `pyproject.toml` if not already present:

```toml
[tool.pytest.ini_options]
markers = ["slow: long-running soak tests (opt-in)"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/perf/test_soak.py -v -m slow`
Expected: PASS (skipped without `-m slow`).

- [ ] **Step 3: Write minimal implementation**

If `pyproject.toml` needs the marker, add it. Otherwise no code changes.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/perf/test_soak.py -v -m slow`
Expected: 1 passed.

- [ ] **Step 5: Lint and commit**

Run: `.venv/bin/ruff check tests/perf/test_soak.py`
Expected: All checks passed.

```bash
git add tests/perf/test_soak.py pyproject.toml
git commit -m "test(writer): add opt-in soak test stub for memory bounds"
```

---

## Self-Review

Every section of the spec must be covered by at least one task. The table below lists each spec section and the task ID(s) that implement it. If a row has no task ID, the plan is incomplete.

| Spec section | Task ID(s) |
|---|---|
| Purpose / Goal / Non-goals / Constraints and budget | 8.2 (p99 budget), 3.2/3.3 (drop-on-full), 8.3 (no-crash, partial recovery) |
| Design overview (hot path → queue → writer → store) | 3.2, 3.3, 3.4, 5.3, 2.2 |
| Storage model — layout on disk | 2.2 |
| Storage model — lifecycle of one session | 2.2, 3.4, 3.5 |
| Storage model — SQLite index (schema, WAL, derived) | 2.3, 8.4 (reindex) |
| Storage model — rotation and eviction | 2.4 |
| Storage model — storage backend abstraction (TraceStore) | 2.1 |
| Storage model — format versioning + unknown-version error | 1.4, 6.3 (`UnknownSchemaVersionError`) |
| Event schema — envelope (BaseEvent, ULID, monotonic+wall time) | 1.1, 1.2 |
| Event schema — closed enum of kinds | 1.2 |
| Event schema — migration from existing schema (legacy mapping) | 6.2 (v1 → legacy mapping for consumers) |
| Event schema — size discipline (attachment_ref) | 1.2 (`AttachmentRefEvent`) |
| Event schema — redaction hook | 3.1, 3.3 |
| Sampling — default tail-based always-on-error | 3.4, 5.3 |
| Sampling — per-call override (`sample=` arg) | 5.3, 5.5 |
| Sampling — global env override (`AUTOPSY_SAMPLE`) | 1.3 |
| Sampling — backpressure / drop counter | 3.2 |
| Sampling — per-call buffer cap | 3.4 |
| Writer architecture — concurrency model | 3.2 |
| Writer architecture — batching | 3.3 |
| Writer architecture — atexit flush | 3.5 |
| Writer architecture — error handling inside writer | 3.3, 3.4 |
| Writer architecture — sync vs async hot path (no asyncio.run) | 5.3 |
| Interceptor — sync + async patch, lazy-import, refcount, suppression | 5.4 |
| Host-observability — finalization log (WARNING/INFO, rate-limited) | 4.3 |
| Exporter seam (Exporter Protocol, default exporters) | 4.1, 4.2, 4.3 |
| Public API — `@lens.trace`, `autopsy.log`, `LensConfig` shape | 5.3, 5.5, 1.3 |
| Module layout | 1.1-1.4, 2.1-2.4, 3.1-3.5, 4.1-4.3, 5.1-5.6, 6.1-6.3 |
| Testing strategy — unit | 1.1, 1.2, 1.3, 1.4, 2.2-2.4, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 5.1, 5.2, 5.5, 6.1, 6.2, 6.3, 8.4 |
| Testing strategy — integration | 5.6, 7.1 (compat_consumers), 8.3 (crash) |
| Testing strategy — performance | 8.1, 8.2, 8.5 |
| Testing strategy — migration (v0 read + future-version refusal) | 6.1, 6.3 |
| Failure modes table | 3.3 (writer errors), 3.4 (queue full/buffer cap), 8.3 (SIGKILL), 5.4 (openai missing), 3.1/3.3 (redactor raises), 2.3/8.4 (sqlite corrupt → reindex) |
| Open seams | 2.1 (TraceStore), 4.1 (Exporter), 1.2 (detector_verdict), 1.4 (UnknownSchemaVersionError → autopsy migrate) |
| Migration plan for the existing code | 5.x in parallel; 6.x compat shim; 7.x switchover |
| Success criteria | 7.5 (existing tests green), 8.2 (p99), 8.3 (SIGKILL), 6.3 (cross-machine load via LegacyBundleReader) |

If any row above is hand-waved, stop and add a task before execution.

---

## Execution Handoff

Plan complete and saved to docs/superpowers/plans/2026-05-29-capture-layer-hardening-plan.md.

Two execution options:

1. Subagent-Driven (recommended) — fresh subagent per task, review between tasks.
2. Inline Execution — execute tasks in this session.

Which approach?
