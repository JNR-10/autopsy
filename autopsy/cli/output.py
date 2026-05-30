"""Rich formatters and JSON serializers for CLI commands."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from autopsy.diagnostics.types import DiagnosisResult

from rich.console import Console
from rich.table import Table

from autopsy.core.compat import LegacyBundleReader


def _detector_fail_name(reader: LegacyBundleReader, session_id: str) -> str:
    """First failing detector name, or '-' if none."""
    manifest_path = reader.root / "sessions" / session_id / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            error_type = manifest.get("error_type") or ""
            if isinstance(error_type, str) and error_type.startswith("detector:"):
                name = error_type[len("detector:"):]
                return name if name else "-"
        except Exception:
            pass
    bundle = reader.load(session_id)
    if bundle is not None:
        for ev in bundle.get("events", []):
            if ev.get("event_type") != "node_error":
                continue
            error_type = ev.get("error_type", "")
            if isinstance(error_type, str) and error_type.startswith("detector:"):
                name = error_type[len("detector:"):]
                return name if name else "-"
    return "-"


def _manifest_field(reader: LegacyBundleReader, session_id: str, key: str) -> Any:
    manifest_path = reader.root / "sessions" / session_id / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
        return manifest.get(key)
    except Exception:
        return None


def extract_detector_verdicts(bundle: dict[str, Any]) -> list[dict[str, str]]:
    """Detector verdict rows from bundle events (v1 kind or legacy node_error)."""
    verdicts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for ev in bundle.get("events", []):
        kind = ev.get("kind") or ev.get("event_type", "")
        if kind == "detector_verdict":
            name = str(ev.get("detector_name", ""))
            verdict = str(ev.get("verdict", ""))
            reason = str(ev.get("reason", ""))
            key = (name, verdict, reason)
            if key not in seen:
                seen.add(key)
                verdicts.append({"name": name, "verdict": verdict, "reason": reason})
        elif ev.get("event_type") == "node_error":
            error_type = ev.get("error_type", "")
            if isinstance(error_type, str) and error_type.startswith("detector:"):
                name = error_type[len("detector:"):]
                reason = str(ev.get("error_message", ""))
                key = (name, "fail", reason)
                if key not in seen:
                    seen.add(key)
                    verdicts.append({"name": name, "verdict": "fail", "reason": reason})
    return verdicts


def extract_errors(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Error nodes from legacy node_error events."""
    errors: list[dict[str, Any]] = []
    for ev in bundle.get("events", []):
        if ev.get("event_type") != "node_error":
            continue
        errors.append({
            "node_id": ev.get("node_id"),
            "error_type": ev.get("error_type"),
            "error_message": ev.get("error_message"),
        })
    return errors


def _show_stats(
    bundle: dict[str, Any],
    reader: LegacyBundleReader | None,
    session_id: str,
) -> dict[str, int]:
    summary = bundle.get("summary") or {}
    dropped = 0
    if reader is not None:
        raw = _manifest_field(reader, session_id, "dropped_events")
        if raw is not None:
            dropped = int(raw)
    return {
        "tokens": int(summary.get("total_tokens", 0)),
        "node_count": int(summary.get("node_count", 0)),
        "dropped_events": dropped,
    }


def _event_preview(ev: dict[str, Any]) -> str:
    for key in ("error_message", "node_name", "content", "output_data", "tool_name"):
        val = ev.get(key)
        if val:
            text = str(val).replace("\n", " ")
            return text[:80] + ("..." if len(text) > 80 else "")
    return ""


def build_show_summary(
    bundle: dict[str, Any],
    reader: LegacyBundleReader | None = None,
) -> dict[str, Any]:
    """Structured summary for `autopsy show --json`."""
    session_id = bundle.get("session_id", "")
    summary = bundle.get("summary") or {}
    error_type = None
    if reader is not None:
        error_type = _manifest_field(reader, session_id, "error_type")
    return {
        "session_id": session_id,
        "agent_name": bundle.get("agent_name", ""),
        "status": summary.get("status", "unknown"),
        "error_type": error_type,
        "duration_ms": int(summary.get("total_duration_ms", 0)),
        "stats": _show_stats(bundle, reader, session_id),
        "detector_verdicts": extract_detector_verdicts(bundle),
        "errors": extract_errors(bundle),
    }


def format_show_human(
    bundle: dict[str, Any],
    *,
    reader: LegacyBundleReader,
    console: Console,
    show_events: bool = False,
) -> None:
    """Render session detail sections for `autopsy show`."""
    session_id = bundle.get("session_id", "")
    summary = bundle.get("summary") or {}
    status = summary.get("status", "unknown")
    error_type = _manifest_field(reader, session_id, "error_type") or "-"
    duration_ms = int(summary.get("total_duration_ms", 0))

    status_color = "green" if status == "success" else (
        "red" if status == "error" else "yellow")

    console.print(f"[bold]Session[/bold] {session_id}")
    console.print(f"[dim]Agent:[/dim] {bundle.get('agent_name', '')}")
    console.print(
        f"[dim]Status:[/dim] [{status_color}]{status}[/{status_color}]")
    console.print(f"[dim]Error type:[/dim] {error_type}")
    console.print(f"[dim]Duration:[/dim] {duration_ms} ms")
    console.print()

    verdicts = extract_detector_verdicts(bundle)
    if verdicts:
        console.print("[bold]Detector verdicts[/bold]")
        table = Table(show_header=True, show_lines=False)
        table.add_column("name")
        table.add_column("verdict")
        table.add_column("reason", overflow="fold")
        for v in verdicts:
            vcolor = "red" if v["verdict"] == "fail" else "green"
            table.add_row(
                v["name"],
                f"[{vcolor}]{v['verdict']}[/{vcolor}]",
                v["reason"],
            )
        console.print(table)
        console.print()

    errors = extract_errors(bundle)
    if errors:
        console.print("[bold]Errors[/bold]")
        err_table = Table(show_header=True, show_lines=False)
        err_table.add_column("node_id", style="dim", overflow="fold")
        err_table.add_column("error_type")
        err_table.add_column("message", overflow="fold")
        for err in errors:
            node_id = str(err.get("node_id") or "")[:12]
            err_table.add_row(
                node_id,
                str(err.get("error_type") or ""),
                str(err.get("error_message") or ""),
            )
        console.print(err_table)
        console.print()

    stats = _show_stats(bundle, reader, session_id)
    console.print("[bold]Stats[/bold]")
    console.print(f"  tokens: {stats['tokens']}")
    console.print(f"  nodes: {stats['node_count']}")
    console.print(f"  dropped: {stats['dropped_events']}")

    if show_events:
        console.print()
        console.print("[bold]Events[/bold]")
        for ev in bundle.get("events", []):
            kind = ev.get("kind") or ev.get("event_type", "?")
            preview = _event_preview(ev)
            line = f"  [dim]{kind}[/dim]"
            if preview:
                line += f" {preview}"
            console.print(line)


def build_session_list_rows(reader: LegacyBundleReader) -> list[dict[str, Any]]:
    """Normalize reader.list() entries for ls table and --json."""
    rows: list[dict[str, Any]] = []
    for s in reader.list():
        summary = s.get("summary") or {}
        session_id = s.get("session_id", "")
        created_ts = float(s.get("created_at", 0))
        created_iso = datetime.fromtimestamp(
            created_ts, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        duration_ms = summary.get("total_duration_ms", s.get("total_duration_ms"))
        if duration_ms is None:
            raw = _manifest_field(reader, session_id, "duration_ms")
            duration_ms = raw if raw is not None else 0
        rows.append({
            "session_id": session_id,
            "agent": s.get("agent_name", ""),
            "status": summary.get("status", s.get("status", "unknown")),
            "errors": int(summary.get("error_count", s.get("error_count", 0))),
            "detector": _detector_fail_name(reader, session_id),
            "duration_ms": int(duration_ms),
            "created": created_iso,
        })
    return rows


def session_list_json(rows: list[dict[str, Any]]) -> str:
    """Serialize session list rows for `autopsy ls --json`."""
    return json.dumps(rows, separators=(",", ":"), sort_keys=True)


def session_summary_json(
    bundle: dict[str, Any],
    *,
    reader: LegacyBundleReader | None = None,
) -> str:
    """Serialize a session bundle summary for `autopsy show --json`."""
    data = build_show_summary(bundle, reader)
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def diagnosis_result_json(result: DiagnosisResult) -> str:
    """Serialize DiagnosisResult for `autopsy diagnose --json`."""
    return json.dumps(asdict(result), separators=(",", ":"), sort_keys=True)


def replay_result_json(result: dict[str, Any]) -> str:
    """Serialize replay result for `autopsy replay --json`."""
    return json.dumps(result, separators=(",", ":"), sort_keys=True, default=str)
