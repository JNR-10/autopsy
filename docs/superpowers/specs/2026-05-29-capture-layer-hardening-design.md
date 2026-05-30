# Capture-Layer Hardening for Production

**Status:** Draft
**Date:** 2026-05-29
**Author:** brainstormed with the project lead
**Sub-project:** 1 of 5 (see Roadmap section)

## Purpose

When code breaks, it raises an exception and you get a stack trace. When an agent "breaks," it returns plausible-looking wrong output — no exception, no log line, nothing for standard observability tools (Sentry, Datadog, log aggregators) to latch onto. That silent-wrong-answer failure mode is the dangerous one in production, and it's invisible by default.

`autopsy` is being repositioned from a hackathon demo into a production-grade `pip install autopsy` library that solves this for agent developers. The roadmap breaks the work into five sub-projects:

1. **Capture-layer hardening** (this spec)
2. Failure detection layer
3. CLI-first diagnose UX
4. Provider abstraction + clean public API + packaging hygiene
5. Demo / dashboard cleanup + production docs

This spec covers only #1. Without a trustworthy, cheap, durable capture layer, everything downstream is built on sand.

## Goal

Make `@lens.trace`, the tracer, and the OpenAI interceptor safe to run in a long-lived production process serving real traffic — without measurable harm to the host application, and producing trace artifacts that can be diagnosed later, on another machine, by another person.

## Non-goals (explicitly out of scope)

- Failure detectors (sub-project #2). The on-disk format reserves a `detector_verdict` event kind so this is forward-compatible, but no detector code ships here.
- CLI redesign (sub-project #3). Existing CLI commands keep working against the new format; they get reshaped later.
- Provider abstraction for diagnosis (sub-project #4). `autopsy/diagnostics/` is not touched.
- Dashboard changes (sub-project #5). If the format change breaks the dashboard reader, we apply the minimum patch needed; the dashboard's future is decided later.
- Cloud storage backends (S3 / GCS). The `TraceStore` interface exists so they can be added; no implementations ship.
- OpenTelemetry / Sentry exporters. An `Exporter` protocol exists; no exporters ship beyond the default file writer.
- Replay engine redesign. The replay engine is adapted to read the new format; it is not rearchitected.
- Demo cleanup, docs overhaul, packaging hygiene. All sub-project #5.

## Constraints and budget

These are non-negotiable for v1 of the capture layer:

- **p99 overhead per traced agent call: at most 5 ms** under typical agent workloads (LLM-bound, not CPU-bound).
- **CPU overhead: at most 1%** of host process CPU time.
- **Zero blocking I/O on the hot path.** No disk write, no network call, no lock acquisition that can block more than a few microseconds.
- **Drop on backpressure, never block.** If the writer queue is full, drop events and increment a counter. Autopsy must never be the reason the host agent gets slower.
- **Never crash the host.** Any exception inside the capture layer is caught, rate-limited via stdlib logging, and never propagated.
- **Acceptable data loss on hard kill: the last batch (under 50 ms worth of events).** We do not fsync per write.

## Design overview

```
+----------------------+      put_nowait     +-----------------+    fsync on
| Host agent process   |  ---------------->  | bounded Queue   |    finalize
| @lens.trace fn       |    (hot path)       | (10k events)    |
| OpenAI SDK (patched) |                     +--------+--------+
+----------------------+                              |
                                                      v
                                          +------------------------+
                                          | daemon writer thread   |
                                          | batch: N=100, T=50ms   |
                                          | drop-on-full counter   |
                                          +-----------+------------+
                                                      |
                                                      v
                                       +------------------------------+
                                       | LocalFilesystemStore         |
                                       | sessions/<id>/manifest.json  |
                                       | sessions/<id>/events.jsonl   |
                                       | sessions/<id>/artifacts/     |
                                       +------------------------------+
                                                      |
                                                      v
                                          +-----------------------+
                                          | SQLite index (derived)|
                                          | index.sqlite          |
                                          +-----------------------+
```

The host calls into the decorator and interceptor on the hot path. They only put_nowait event objects onto a bounded in-process queue. A single daemon thread drains the queue in batches and writes to disk. On session finalization the writer fsyncs the events file and seals the manifest. The SQLite index is a derived secondary structure; it is rebuilt from the on-disk sessions if lost.

## Storage model

### Layout on disk

```
<root>/
  sessions/
    <session_id>/
      manifest.json          # versioned metadata, written atomically
      events.jsonl           # append-only event log (gz after finalize)
      artifacts/             # large blobs spilled out of events
        <content_hash>.bin
  index.sqlite               # derived lookup table, rebuildable
```

`<root>` is selected at startup using the same fallback chain that exists today: the `AUTOPSY_SESSION_DIR` env var, then `~/.autopsy`, then `./.autopsy`, then a temp directory. The first writable candidate wins. This is preserved from the existing code.

### Lifecycle of one session

1. A traced call begins. A new directory `<root>/sessions/<session_id>/` is created lazily on first event flush (not at call entry, so calls that never produce events because they are sampled out create no disk artifacts).
2. The writer thread streams events into `events.jsonl` in append-only mode. The manifest is written once at session start with `status="live"` and re-written atomically at finalize with the sealed status.
3. On finalize: a final batch flush, an fsync on `events.jsonl`, manifest is sealed (`status="ok"|"error"|"partial"`, end time, counts, dropped-events counter).
4. After finalize (default: immediately, configurable to delay): `events.jsonl` is gzip-compressed in place to `events.jsonl.gz`. The manifest stays uncompressed so listing is fast.
5. The SQLite index is updated with a single row insert.

### SQLite index

A single file at `<root>/index.sqlite` with one table:

```sql
CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  start_time_ns INTEGER NOT NULL,
  end_time_ns INTEGER,
  duration_ms INTEGER,
  status TEXT NOT NULL,        -- live | ok | error | partial
  error_type TEXT,
  event_count INTEGER,
  dropped_events INTEGER DEFAULT 0,
  pinned INTEGER DEFAULT 0,
  path TEXT NOT NULL,
  schema_version INTEGER NOT NULL
);
CREATE INDEX idx_sessions_start_time ON sessions(start_time_ns DESC);
CREATE INDEX idx_sessions_status ON sessions(status);
```

The index is **derived**: if it is missing or corrupted, `autopsy reindex` walks the sessions directory and rebuilds it from the manifests. The source of truth is always the per-session files on disk.

All writes to the SQLite index (inserts at finalize and deletes during eviction) happen on the writer thread. Reads happen from any thread the CLI / dashboard runs in; SQLite's built-in WAL mode makes this safe. Index writes use a short-held connection opened per write so the writer thread does not hold a long-lived handle.

### Rotation and eviction

Two caps, both configurable, evaluated by the writer thread on a low-frequency tick (default: every 60 seconds):

- `max_total_disk_mb` (default 2048): when exceeded, delete oldest non-pinned sessions until under cap.
- `max_session_age_days` (default 30): sessions older than this are deleted regardless of pinning unless explicitly pinned.

Eviction deletes the entire `<session_id>/` directory and the corresponding index row in one transaction.

### Storage backend abstraction

A `TraceStore` Protocol exists with methods `write_events`, `finalize_session`, `list_sessions`, `load_session`, `delete_session`, `reindex`. `LocalFilesystemStore` is the only built-in implementation in v1. Adding S3 / GCS backends is a follow-up; this spec only defines the seam.

### Format versioning

The manifest carries `autopsy_format_version: 1`. On read, if a future autopsy encounters an unknown version it refuses to load with a clear error message and points at a migration command (`autopsy migrate <path>`), which does not need to exist in v1 but the error message reserves the convention.

**No `autopsy migrate` command ships in this sub-project.** Legacy v0 sessions are handled at read-time by `LegacyBundleReader` (compatibility mode). They are never rewritten to v1 on disk. After `max_session_age_days` (default 30) of eviction they naturally disappear. This is acceptable because the current user base has no v0 sessions older than that; if the policy needs to change later, the seam exists.

## Event schema

### Event envelope

Every event is a Pydantic v2 model with this common envelope:

```python
class BaseEvent(BaseModel):
    event_id: str           # ULID (sortable, no coordination)
    parent_id: str | None   # event_id of enclosing span, None at session root
    session_id: str
    trace_id: str           # equals session_id by default; separable for cross-process
    timestamp_ns: int       # monotonic-derived where possible; wall clock fallback
    kind: EventKind         # closed enum, see below
    status: Literal["ok", "error", "unset"] = "unset"
    attributes: dict[str, Any] = {}
```

`event_id` is a 26-character Crockford ULID. We use ULIDs rather than UUID4 because they are time-ordered, which makes the events file naturally sorted on disk and avoids needing a separate sequence number.

`timestamp_ns`: at session start we record both `time.monotonic_ns()` and `time.time_ns()` in the manifest. Per-event timestamps are derived from the monotonic clock plus the wall-clock offset, giving monotonic ordering with wall-clock-accurate absolute times.

`status` uses OpenTelemetry's vocabulary (`ok`, `error`, `unset`) so an exporter is a thin adapter.

### Event kinds (closed enum, schema version 1)

```
session_start    session_end
agent_start      agent_end           # an @lens.trace call; nests
llm_request      llm_response        # one pair per intercepted LLM call
tool_call_start  tool_call_end       # tool invocations (separate from LLM)
error                                 # captured exception at any level
log                                   # user-emitted via autopsy.log(...)
attachment_ref                        # pointer to artifacts/<hash>.bin
detector_verdict                      # RESERVED for sub-project #2; no producer in v1
```

The enum is closed at version 1. Adding a new kind requires a schema version bump and a documented migration.

### Migration from the existing schema

The current code uses event types like `node_start`, `node_end`, `node_error`, `tool_call`, `tool_result`, `agent_handoff`. The new schema unifies these:

- `node_start` with `node_type="agent"` becomes `agent_start`. Other `node_type` values are folded into `agent_start` with `attributes.role` carrying the original type. (Only `agent`, `llm`, `tool`, `user` are used today; only `agent` is meaningful as a span; the others were artifacts of the dashboard model.)
- `node_end` becomes `agent_end`.
- `node_error` becomes an `error` event with the relevant `parent_id`.
- `tool_call` / `tool_result` become `tool_call_start` / `tool_call_end`.
- `agent_handoff` is dropped: it was always implicit in nested `agent_start` events with different `attributes.agent_name`. No information is lost.

This is a breaking change to the on-disk format. Existing sessions (format version 0, implicit) are not auto-migrated; the new reader explicitly recognizes them and reads them in a compatibility mode that maps the old shapes into the new event types on the fly, never writing back. After 30 days (the default `max_session_age_days`) all legacy sessions naturally age out.

### Size discipline

Any individual field (a message content, a tool result, a traceback) over a configurable byte threshold (default 64 KB) is replaced with an `attachment_ref` event. The original event keeps a short preview (`<= 512 bytes`) and the SHA256 content hash. The full payload is written to `<session>/artifacts/<sha256>.bin`. Content-addressing means a hot prompt that recurs across thousands of calls is stored once per session.

### Redaction hook

A single user-configurable callable `redactor: Callable[[BaseEvent], BaseEvent | None]` runs on each event before write. Returning `None` drops the event entirely. The default implementation:

- Scrubs values that match common secret patterns (`sk-...`, `Bearer ...`, `AWS...`, OAuth-shaped tokens) anywhere in `attributes`, replacing them with `"[REDACTED:secret]"`.
- Does **not** attempt PII detection. PII redaction is a downstream concern; we make it pluggable, not built-in.

The redactor runs on the writer thread, not the hot path.

## Sampling

### Default mode: tail-based, always-on-error

Every traced agent call records events through the standard hot-path → queue → writer pipeline. The writer maintains a per-session in-memory buffer of events that have been drained from the queue but not yet committed to disk. On call exit:

- If the call raised, the writer flushes that session's buffer to `events.jsonl` and seals the manifest with `status="error"`.
- If the call succeeded under `sample="errors"`, the writer discards the buffer. **No disk artifact is created at all** — no `<session_id>/` directory, no `manifest.json`, no `events.jsonl`, no SQLite index row. A 10k-calls-per-minute production agent that never errors creates zero disk activity from autopsy.

Consequence: under `sample="errors"`, `autopsy ls` only shows error and partial sessions. Success counts come from the host's log pipeline (the finalization log line is emitted at INFO for successful sessions, rate-limited to one per agent per 60 seconds). This is the right tradeoff for production-scale tracing — autopsy is an *exception observatory*, not a metrics system. Teams that want success-rate metrics should use a metrics system.

The writer is the single point that decides "keep or discard," because it is the only place with the full picture (the call's final outcome, the in-memory event log, and the disk). The hot path does not know whether a call will be kept; it just enqueues.

This is a conscious tradeoff: under `sample="errors"`, successful sessions hold their events in writer-thread memory for the duration of the call. Memory cost is bounded by `max_in_flight_buffer_mb` per concurrent session (see "Per-call buffer cap" below). For a typical agent workload (sub-second to a few seconds per call, low MB per call), this is negligible. For a long-running agent that streams many events, the buffer cap forces an early spill to disk so memory stays bounded.

Later (sub-project #2), "the call was flagged by a detector" will be a second signal that triggers flush. The mechanism is the same; only the trigger differs.

### Per-call override

The decorator accepts a `sample` argument:

```python
@lens.trace(sample="all")        # always write to disk
@lens.trace(sample="errors")     # explicit form of the default
@lens.trace(sample=0.01)         # 1% head-based rate, in addition to errors
@lens.trace(sample="off")        # decorator is a no-op
```

When `sample` is a float, it is a head-based rate applied at call entry: with probability `p` the call is marked "keep-success" and its successful trace is flushed alongside any errored ones. Errored calls are always kept regardless of `p`.

### Global env override

`AUTOPSY_SAMPLE=all|errors|off|<float>` sets the default for every decorated function in the process. Per-call decorator args win over the env.

### Backpressure (always on, independent of sampling)

If the writer queue is over its high-water mark when an event is enqueued, the event is dropped and a `dropped_events` counter on the live session is incremented. The counter is included in the manifest at finalize. Backpressure never blocks the host.

### Per-call buffer cap

If a single live call accumulates more than `max_in_flight_buffer_mb` (default 10) of pending events before exit, the writer spills that call's buffer to disk early, treating it as if sampling kicked in. The session is marked `partial: true` in the manifest. This prevents a runaway agent from filling host memory.

## Writer architecture

### Concurrency model

- **One daemon thread per process** (`threading.Thread(daemon=True)`), singleton, started lazily on the first traced call. Survives event-loop weirdness because it does not touch the loop.
- **One `queue.Queue`** with `maxsize=10_000`. Hot path uses `put_nowait`; on `queue.Full`, increments a process-global dropped counter, attributes it to the active session at finalize time.
- **Refcounted lifecycle:** the thread starts on first session, stays alive until process exit. The OpenAI interceptor patch is also refcounted (it already is in the existing code); we keep that.

### Batching

The writer drains up to `flush_batch_size` events (default 100) or waits up to `flush_interval_ms` (default 50) before processing a batch. Both are configurable via `LensConfig` and env vars.

Processing a batch is:

1. Group events by `session_id`.
2. For each group, append the events to that session's **in-memory buffer**.
3. Apply the redactor to each event as it enters the buffer.
4. If the session's effective sample mode is `"all"` or the session has already been promoted to `kept` (because an earlier event was an `error` or a head-rate roll selected it), spill the buffer to disk: open the cached append-mode file handle to `events.jsonl`, write newline-delimited JSON (`orjson` preferred if installed, stdlib `json` as fallback — neither becomes a new hard dep), flush, do not fsync.
5. Otherwise (`sample="errors"` and the session has not been promoted), keep the events in the in-memory buffer.

On `agent_end` for the call's root: if the session is in `kept` state, spill any remaining buffered events and finalize. If not, discard the buffer and clean up — no disk artifact ever existed for this session.

fsync happens only on session finalize and on process atexit, never per batch.

The "promoted" / "kept" / "discarded" state machine is the single place where the sampling decision lives. It is small, testable in isolation, and is the same code path that sub-project #2's detectors will plug into.

### atexit flush

An `atexit` handler signals the writer to drain remaining events with a bounded 2-second timeout. Any session that did not call `finalize()` (e.g., because the process was killed) is marked `status="partial"` in its manifest if reachable, otherwise the next reindex run will mark it `partial`.

### Error handling inside the writer

Every operation inside the writer thread is wrapped in `try/except Exception`. On failure:

- The exception is logged via stdlib `logging` to `autopsy.writer` at WARNING.
- Logs are rate-limited (token bucket: at most one log per 60 seconds per error category).
- The writer thread does not die. If a specific session is unwritable, that session is marked `partial` and the writer moves on to others.

### Sync vs async hot path

The decorator currently has two wrappers: an async wrapper for coroutine functions and a sync wrapper that spins up `asyncio.run(...)` for sync functions. The sync wrapper's "spin up an event loop" path is fundamentally wrong for production (it cannot be used inside an existing loop, it costs ~ms of overhead, and it forces sync agents to pay an asyncio tax).

The new design removes the event loop from the hot path entirely:

- The decorator never `await`s the writer. It calls a sync `session.record_event(ev)` method that does the `put_nowait` and returns immediately. Both the sync and async wrappers use the same call.
- The async wrapper still uses `async def` for `await fn(...)`, but the trace emission itself is synchronous.
- The sync wrapper just calls `fn(*args, **kwargs)` directly; no `asyncio.run`.

This fixes a real correctness bug in the current code (the sync wrapper calls `fn(*args, **kwargs)` directly when inside a running loop, dropping all tracing silently — see the `RuntimeError` branch in `decorator.py`).

### Interceptor

The interceptor today only patches `openai.resources.chat.completions.AsyncCompletions.create`. In production we also need:

- `openai.resources.chat.completions.Completions.create` (the sync variant).
- The Responses API: `openai.resources.responses.Responses.create` and the async equivalent (if installed openai SDK version supports it).
- Graceful no-op when the openai package is absent (currently it imports openai unconditionally inside `install`; the new code lazy-imports and silently no-ops if missing — needed because we want to drop `openai` from being a hard dep down the line, though this spec does not change deps).

The patch stays refcounted (it already is). The `_in_diagnostics_call` ContextVar to suppress nested diagnostic LLM calls stays.

## Host-observability integration

One structured log line is emitted via stdlib `logging` on the logger named `autopsy` whenever a session finalizes:

- **WARNING level** for `status in {"error", "partial"}`.
- **INFO level** for `status == "ok"`. Rate-limited to at most one per agent name per 60 seconds (so a high-QPS healthy stream does not flood logs).

The log uses `LoggerAdapter` with `extra=` so structured-log handlers receive the fields as keys, not interpolated text:

```
extra = {
  "session_id":     "01HXY...",
  "agent_name":     "my_agent",
  "status":         "error",
  "error_type":     "ContextOverflowError",
  "duration_ms":    1240,
  "event_count":    47,
  "dropped_events": 0,
  "trace_path":     "/var/lib/autopsy/sessions/01HXY...",
  "autopsy_version": "0.2.0"
}
```

The message string is human-readable:

```
autopsy: agent=my_agent status=error duration=1240ms session=01HXY... run 'autopsy diagnose 01HXY...' to investigate
```

Off-switch: `AUTOPSY_LOG_FINALIZATION=0` or `LensConfig(log_finalization=False)`. Default on.

### Exporter seam

Internally the writer fans events out through an `Exporter` Protocol:

```python
class Exporter(Protocol):
    def export(self, batch: list[BaseEvent]) -> None: ...
    def finalize_session(self, manifest: Manifest) -> None: ...
```

The default exporter is `FileSystemExporter` (writes `events.jsonl`, `manifest.json`, `artifacts/`). The structured-log emission lives in a `LoggingExporter` that is enabled by default. Both are registered on the writer.

Future OpenTelemetry and Sentry exporters slot in here without touching the writer. **No exporters beyond `FileSystemExporter` and `LoggingExporter` ship in this sub-project.**

## Public API changes

The user-facing surface stays minimal:

```python
from autopsy import lens, LensConfig

# Same as today
@lens.trace
async def my_agent(query): ...

# New: explicit sampling
@lens.trace(sample="all")
@lens.trace(sample="errors")
@lens.trace(sample=0.05)
@lens.trace(sample="off")

# New: user log breadcrumbs that become `log` events
from autopsy import log
log("retry_attempt", attempt=3, reason="rate_limited")
```

`LensConfig` is reshaped. New fields (all with sensible defaults):

```python
@dataclass
class LensConfig:
    session_dir: str | None = None             # preserved from current LensConfig

    # Capture-layer knobs (new)
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
    redactor: Callable[[BaseEvent], BaseEvent | None] | None = None
```

**Removed (breaking change):** `gmi_api_key`, `google_ai_api_key`, `port`, `auto_diagnose`, `model`. These belong to the diagnose layer, not capture. Keeping them on `LensConfig` would re-mix the responsibilities this refactor exists to separate. They will reappear on a `DiagnoseConfig` in sub-project #4. No deprecation period: the current users are on hackathon code; this is the moment to break cleanly.

`autopsy.log(name: str, **attributes)` is the new structured-breadcrumb API. It emits a `log` event attached to the current span (uses the same ContextVars the decorator uses). No-op if no session is active. Never raises.

## Module layout

```
autopsy/core/
  events.py           # Pydantic v2 models, EventKind enum
  ulid.py             # tiny ULID generator (no new dep)
  config.py           # LensConfig dataclass + env loader
  decorator.py        # @lens.trace, sync + async wrappers
  interceptor.py      # OpenAI SDK monkey-patch (sync + async, refcounted)
  context.py          # ContextVars for current session, parent span, suppression
  session.py          # Session lifecycle (renamed from tracer.py)
  writer.py           # daemon thread + bounded queue + batching
  store/
    __init__.py       # TraceStore Protocol
    local_fs.py       # LocalFilesystemStore
    sqlite_index.py   # SQLite derived index
  exporters/
    __init__.py       # Exporter Protocol
    file.py           # FileSystemExporter
    logging.py        # LoggingExporter
  redact.py           # default redactor + secret patterns
  errors.py           # internal exception types
  compat.py           # LegacyBundleReader: bilingual v0/v1 reader for consumers
```

This is a meaningful refactor of the current single-file `tracer.py` (485 lines doing too much). Each module has one job and a small surface.

## Testing strategy

### Unit tests

- Event schema: every event kind round-trips through JSON; unknown kinds on read are rejected; oversized fields are correctly spilled to attachments.
- ULID: monotonicity within the same millisecond, sortability, encoding length.
- Queue + writer: drops on full and counts; batches respect `flush_batch_size` and `flush_interval_ms`; atexit drains within 2 seconds.
- Sampling: `"errors"` discards on success; `"all"` keeps both; numeric rate is statistically correct within tolerance; `"off"` is a true no-op.
- Redactor: known secret patterns are scrubbed; non-matching strings pass through; a redactor that raises is caught.
- Store: write/read roundtrip; reindex rebuilds a missing SQLite index; eviction respects pinning; size cap evicts oldest non-pinned.

### Integration tests

- End-to-end: an async agent that uses the openai SDK against a stub server, traced with default sampling. On success, no disk artifact. On exception, full session present with correct event ordering and parent links.
- Sync agent: same, with a sync function decorated. Verify no asyncio is involved.
- Nested agents: outer `@lens.trace` calls inner `@lens.trace`. One session, correct parent chain.
- Two concurrent sessions in the same process. Events do not cross sessions.
- Process kill mid-session: kill -9 the test process. Reindex correctly classifies the abandoned session as `partial`.
- Interceptor: sync and async openai SDK calls both produce `llm_request`/`llm_response` pairs.

### Performance tests

- A trivial traced async function that does 10 LLM calls (mocked, zero-latency) runs `N=1000` times. Median overhead per call is measured. Target: under 5ms p99. CI gates this.
- Queue overflow test: write 100k events with the writer artificially slowed. Verify drops are counted, host never blocks, no events from finalized sessions are lost.
- Memory test: 24-hour soak with a continuously-traced agent. RSS growth bounded by `max_in_flight_buffer_mb` times concurrent sessions.

### Migration tests

- A directory of legacy (format version 0) sessions is read correctly in compatibility mode.
- A future-versioned manifest is refused with the documented error message.

## Failure modes and how the design handles them

| Failure | Behavior |
|---|---|
| Disk full | Writer logs once per minute, drops events, marks active sessions `partial` on finalize. Host agent unaffected. |
| Queue full (writer slow) | `put_nowait` increments dropped counter; manifest carries the count. Host unaffected. |
| Writer thread crashes | Caught and logged; thread is restarted by the next `put_nowait`. Worst case: small batch lost. |
| Host process killed (SIGKILL) | Last batch (under 50ms) lost; events.jsonl may have a partial trailing line; reader skips malformed lines with warning; reindex marks session `partial`. |
| openai package not installed | Interceptor lazy-import fails silently; tracing of LLM calls is skipped; agent tracing still works. |
| Redactor raises | Caught; event is dropped (fail-closed: better to lose an event than leak a secret); logged. |
| SQLite index corrupted | Caught on read; users see a clear error pointing to `autopsy reindex`; reindex rebuilds from manifests. |
| Two processes share the same session dir | Each writes to its own session subdirectories; index writes use SQLite's built-in locking. No cross-process coordination needed beyond what SQLite provides. |
| ContextVars do not propagate (some library breaks them) | Decorator detects missing parent on a non-root call, attaches the event to the session root with a warning attribute. No crash. |

## Open seams (not built, but designed for)

- `TraceStore` Protocol: future S3 / GCS backends.
- `Exporter` Protocol: future OTel / Sentry exporters.
- `detector_verdict` event kind: sub-project #2 detectors.
- `autopsy migrate <path>` command: future schema bumps.
- Multi-process trace_id: `trace_id` is separate from `session_id` precisely to allow stitching traces across services later. Not used in v1.

## Migration plan for the existing code

This is a substantial refactor of `autopsy/core/`. The dashboard, CLI, and diagnostics modules consume the tracer's output. To keep the project working through the refactor:

1. **Define new events, store, writer in parallel** without removing the old `tracer.py`. New code lives in the module layout above; old `tracer.py` stays for one PR.
2. **Add `LegacyBundleReader` to `autopsy/core/compat.py`.** It is a *capture-layer-owned* adapter that reads either the new on-disk format (v1) or the old format (implicit v0) and returns the old `TraceBundle` dict shape that the dashboard and diagnostics consume today. This is the seam that lets us refactor the capture layer without simultaneously rewriting the consumers. Consumers are sub-project #5's problem.
3. **Switch the decorator over to the new session / writer.** Run the test suite. Run both demo agents.
4. **Delete the old `tracer.py`** and the old in-process event queue / drain task. `LegacyBundleReader` stays — it is the consumers' read API until sub-project #5.
5. **Bump `autopsy_format_version` from implicit 0 to 1.** Reader stays bilingual; writer only emits v1.

Each step is a separate PR. The project is releasable after each one.

## Success criteria

- All existing tests pass against the new capture layer (with a small `LegacyBundleReader` shim feeding the unchanged consumers).
- New unit + integration + perf tests added per the testing strategy section, all green.
- p99 overhead per traced call is under 5 ms in the perf test.
- Host process killed with SIGKILL mid-session leaves recoverable trace files (reindex classifies them `partial`).
- A trace captured on machine A can be tarred up, untarred on machine B, and loaded by `LegacyBundleReader.load(<path>)` without the source code present.

## Roadmap context

After this sub-project lands, the order of the remaining work is:

2. **Failure detection layer** — pluggable detectors that flag traces as semantically failing even when no exception was raised. Consumes the new event stream.
3. **CLI-first diagnose UX** — `autopsy ls / show / diagnose / tail / export / import`, Rich-formatted for humans, `--json` for scripts. The CLI becomes the daily-driver surface.
4. **Provider abstraction, public API, packaging hygiene** — pluggable diagnose providers, drop hard deps on sponsor SDKs, semver, CI/CD, PyPI release flow.
5. **Demo / dashboard cleanup + production docs** — separate demo code out of the library, decide the dashboard's fate, write production-grade docs.

Each sub-project gets its own spec.





