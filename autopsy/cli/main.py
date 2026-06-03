"""autopsy CLI commands.

Commands:
  autopsy run <script.py>     start server + run user agent + open browser
  autopsy serve               start server only
  autopsy ls                  list saved sessions (canonical)
  autopsy sessions            alias for ls
  autopsy show <id>           show session detail
  autopsy diagnose <id>       diagnose a saved session
  autopsy tail <id>           tail session events (live or last N)
  autopsy export              export sessions to tarball
  autopsy import <file>       import sessions from tarball/JSON
  autopsy replay <id>         replay a saved session (simulated by default)
  autopsy detectors [id]      list detectors or re-run them on a session
  autopsy clean               delete old sessions
  autopsy deploy              deprecated alias for export
"""
from __future__ import annotations

import asyncio
import logging
import os
import runpy
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

console = Console()


def _get_port() -> int:
    try:
        return int(os.environ.get("AUTOPSY_PORT", "7823"))
    except ValueError:
        return 7823


def _get_host() -> str:
    return os.environ.get("AUTOPSY_HOST", "127.0.0.1")


def _session_dir() -> Path:
    from autopsy.core.config import default_session_dir
    return default_session_dir()


def _store_root() -> Path:
    sd = _session_dir()
    return sd.parent if sd.name == "sessions" else sd


def _bundle_reader():
    from autopsy.core.compat import LegacyBundleReader
    return LegacyBundleReader(root=_store_root())


@click.group()
@click.version_option(package_name="autopsy")
def cli() -> None:
    """autopsy - your agent died. here's why."""


def _require_server() -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:
        raise click.ClickException(
            "The dashboard server requires optional dependencies: "
            "pip install autopsy[server]"
        ) from exc


@cli.command("run")
@click.argument("script", type=click.Path(exists=True, dir_okay=False))
@click.option("--port", default=None, type=int, help="Server port (default: 7823)")
@click.option("--host", default=None, help="Server host (default: 127.0.0.1)")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option(
    "--demo",
    is_flag=True,
    help="Enable hackathon demo routes (fix markers for examples)",
)
def cmd_run(
    script: str, port: int, host: str, no_browser: bool, debug: bool, demo: bool,
) -> None:
    """Run an agent script with autopsy tracing + dashboard."""
    _require_server()
    if demo:
        os.environ["AUTOPSY_DEMO"] = "1"
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    port = port or _get_port()
    host = host or _get_host()
    _start_server_and_run(script, port=port, host=host, open_browser=not no_browser)


@cli.command("serve")
@click.option("--port", default=None, type=int)
@click.option("--host", default=None)
@click.option("--no-browser", is_flag=True)
def cmd_serve(port: int, host: str, no_browser: bool) -> None:
    """Start the dashboard server without running an agent."""
    _require_server()
    port = port or _get_port()
    host = host or _get_host()
    _start_server(port=port, host=host, open_browser=not no_browser)


def _start_server(port: int, host: str, open_browser: bool) -> None:
    """Start uvicorn server in the foreground."""
    _require_server()
    import uvicorn
    from autopsy.server.app import app
    if open_browser and not os.environ.get("AUTOPSY_NO_BROWSER"):
        threading.Timer(0.8, lambda: _open_browser(host, port)).start()
    console.print(
        f"[bold]autopsy[/bold] listening at "
        f"[link]http://{host}:{port}[/link]")
    config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                            access_log=False)
    server = uvicorn.Server(config)
    server.run()


def _open_browser(host: str, port: int) -> None:
    try:
        url = f"http://{host}:{port}"
        webbrowser.open(url)
    except Exception:
        pass


def _start_server_and_run(script: str, *, port: int, host: str, open_browser: bool) -> None:
    """Run uvicorn in a background thread, then run the user script in the main thread."""
    _require_server()
    import uvicorn
    from autopsy.server.app import app

    config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                            access_log=False)
    server = uvicorn.Server(config)

    server_thread = threading.Thread(
        target=lambda: server.run(), daemon=True, name="autopsy-server")
    server_thread.start()

    # Wait briefly for server to become ready.
    for _ in range(40):
        time.sleep(0.05)
        if getattr(server, "started", False):
            break

    console.print(
        f"[bold]autopsy[/bold] listening at "
        f"[link]http://{host}:{port}[/link]\n"
        f"Running [cyan]{script}[/cyan]...\n")

    if open_browser and not os.environ.get("AUTOPSY_NO_BROWSER"):
        threading.Timer(0.5, lambda: _open_browser(host, port)).start()

    # Run the user script.
    abs_script = str(Path(script).resolve())
    sys.path.insert(0, str(Path(abs_script).parent))
    exit_code = 0
    try:
        runpy.run_path(abs_script, run_name="__main__")
    except SystemExit as e:
        exit_code = e.code or 0
    except KeyboardInterrupt:
        console.print("[yellow]script interrupted[/yellow]")
    except Exception:
        console.print_exception()
        exit_code = 1

    # Print session summary.
    try:
        sessions = _bundle_reader().list()
        if sessions:
            console.print(
                f"\n[green]✓[/green] {len(sessions)} session(s) recorded. "
                "Dashboard stays open - press Ctrl+C to exit.\n")
    except Exception:
        pass

    # Keep the server alive until user kills it.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("[dim]bye[/dim]")
    sys.exit(exit_code)


def _cmd_ls(*, as_json: bool) -> None:
    """List recorded sessions (human table or --json)."""
    from autopsy.cli.output import build_session_list_rows, session_list_json

    reader = _bundle_reader()
    rows = build_session_list_rows(reader)
    if not rows:
        if as_json:
            click.echo(session_list_json([]))
            return
        console.print(
            "[yellow]No sessions yet. "
            "Run [cyan]autopsy run agent.py[/cyan] to record one.[/yellow]")
        return
    if as_json:
        click.echo(session_list_json(rows))
        return
    from datetime import datetime

    table = Table(title="autopsy sessions", show_lines=False)
    table.add_column("session_id", style="dim", overflow="fold")
    table.add_column("agent")
    table.add_column("status")
    table.add_column("errors", justify="right")
    table.add_column("detector")
    table.add_column("duration_ms", justify="right")
    table.add_column("created", style="dim")
    for row in rows[:50]:
        created = datetime.fromisoformat(
            row["created"].replace("Z", "+00:00"),
        ).strftime("%Y-%m-%d %H:%M:%S")
        status = row["status"]
        color = "green" if status == "success" else (
            "red" if status == "error" else "yellow")
        table.add_row(
            row["session_id"][:18],
            row["agent"][:30],
            f"[{color}]{status}[/{color}]",
            str(row["errors"]),
            row["detector"],
            str(row["duration_ms"]),
            created,
        )
    console.print(table)


@cli.command("ls")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON array to stdout")
def cmd_ls(as_json: bool) -> None:
    """List recorded sessions."""
    _cmd_ls(as_json=as_json)


@cli.command("sessions")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON array to stdout")
@click.pass_context
def cmd_sessions(ctx: click.Context, as_json: bool) -> None:
    """List recorded sessions (alias for ls)."""
    ctx.invoke(cmd_ls, as_json=as_json)


@cli.command("show")
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON summary to stdout")
@click.option("--events", "show_events", is_flag=True, help="Include compact event timeline")
def cmd_show(session_id: str, as_json: bool, show_events: bool) -> None:
    """Show session detail: summary, detector verdicts, errors, stats."""
    from autopsy.cli.output import format_show_human, session_summary_json
    from autopsy.cli.resolve import resolve_session_id

    reader = _bundle_reader()
    sid = resolve_session_id(reader, session_id)
    bundle = reader.load(sid)
    if bundle is None:
        raise click.ClickException(f"session {session_id!r} not found")

    if as_json:
        click.echo(session_summary_json(bundle, reader=reader))
        return

    format_show_human(
        bundle, reader=reader, console=console, show_events=show_events,
    )


def _make_diagnose_agent(model: str, bundle: dict):
    """Pick diagnose provider (overridable in tests)."""
    from autopsy.diagnostics.provider import resolve_diagnose_provider

    return resolve_diagnose_provider(model_choice=model, bundle=bundle)


@cli.command("diagnose")
@click.argument("session_id")
@click.option("--node", "node_id", default=None, help="Specific node to diagnose")
@click.option("--model", default="auto",
              type=click.Choice([
                  "auto", "heuristic", "openai", "anthropic",
                  "gmi", "gemini", "ollama",
              ]))
@click.option("--json", "as_json", is_flag=True, help="Emit DiagnosisResult JSON to stdout")
def cmd_diagnose(session_id: str, node_id: str, model: str, as_json: bool) -> None:
    """Diagnose a saved session with the AI debugger."""
    from autopsy.cli.output import diagnosis_result_json
    from autopsy.cli.resolve import resolve_session_id

    reader = _bundle_reader()
    sid = resolve_session_id(reader, session_id)
    bundle = reader.load(sid)
    if bundle is None:
        raise click.ClickException(f"session {session_id!r} not found")

    agent = _make_diagnose_agent(model, bundle)
    if not as_json:
        console.print(f"[dim]Diagnosing with {agent.name}...[/dim]")
    result = asyncio.run(agent.diagnose(bundle, node_id))
    if as_json:
        click.echo(diagnosis_result_json(result))
        return
    console.print()
    console.print(f"[bold]🔍 Root cause[/bold]\n{result.root_cause}\n")
    console.print(
        f"[dim]Node:[/dim] {result.affected_node_name} "
        f"([dim]{result.affected_node_id}[/dim])")
    console.print(f"[dim]Category:[/dim] {result.error_category}")
    console.print(f"[dim]Confidence:[/dim] {result.confidence:.0%}\n")
    console.print(f"[bold]💡 Fix[/bold]\n{result.fix_suggestion}\n")
    if result.fix_code_snippet:
        console.print("[bold]Code snippet[/bold]")
        console.print(result.fix_code_snippet)
        console.print()
    if result.latency_insight:
        console.print(
            f"[bold]⚡ Latency[/bold]\n{result.latency_insight}")
        if result.estimated_latency_savings_ms:
            console.print(
                f"[dim]Est. savings: "
                f"{int(result.estimated_latency_savings_ms)}ms[/dim]")


@cli.command("detectors")
@click.argument("session_id", required=False, default=None)
@click.option("--list", "list_only", is_flag=True, help="List built-in detectors and exit")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON")
def cmd_detectors(session_id: str | None, list_only: bool, as_json: bool) -> None:
    """List built-in detectors or re-run them on a saved v1 session."""
    import json as json_mod

    from autopsy.core.compat import load_session_events_for_detectors
    from autopsy.core.config import load_config_from_env
    from autopsy.detectors.catalog import detector_catalog
    from autopsy.detectors.registry import resolve_enabled
    from autopsy.detectors.runner import run_detectors

    if list_only or session_id is None:
        rows = [
            {
                "name": d.name,
                "description": d.description,
                "default_enabled": d.default_enabled,
            }
            for d in detector_catalog()
        ]
        if as_json:
            click.echo(json_mod.dumps(rows, indent=2))
            return
        table = Table(title="Built-in detectors")
        table.add_column("name", style="cyan")
        table.add_column("default")
        table.add_column("description")
        for d in detector_catalog():
            table.add_row(
                d.name,
                "yes" if d.default_enabled else "no",
                d.description[:72],
            )
        console.print(table)
        if session_id is None:
            return

    from autopsy.cli.resolve import resolve_session_id

    reader = _bundle_reader()
    sid = resolve_session_id(reader, session_id)
    try:
        events, outcome = load_session_events_for_detectors(reader, sid)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    if outcome not in ("ok", "error", "partial", "live"):
        outcome = "ok"
    cfg = load_config_from_env()
    verdicts = run_detectors(
        events=events,
        outcome=outcome,
        session_id=sid,
        trace_id=sid,
        parent_id=None,
        detectors=resolve_enabled(cfg),
    )
    if as_json:
        click.echo(json_mod.dumps([v.model_dump() for v in verdicts], indent=2))
        return
    if not verdicts:
        console.print("[green]No detector failures or warnings.[/green]")
        return
    table = Table(title=f"Detector results — {sid[:18]}")
    table.add_column("detector")
    table.add_column("verdict")
    table.add_column("reason")
    for v in verdicts:
        color = "red" if v.verdict == "fail" else "yellow"
        table.add_row(
            v.detector_name,
            f"[{color}]{v.verdict}[/{color}]",
            v.reason[:80],
        )
    console.print(table)


@cli.command("tail")
@click.argument("session_id")
@click.option("--lines", default=20, type=int, help="Last N events for finalized sessions")
@click.option("--json", "as_json", is_flag=True, help="Emit NDJSON events to stdout")
def cmd_tail(session_id: str, lines: int, as_json: bool) -> None:
    """Tail session events (last N for finalized, poll for live)."""
    from autopsy.cli.resolve import resolve_session_id
    from autopsy.cli.tail import tail_session

    reader = _bundle_reader()
    sid = resolve_session_id(reader, session_id)
    try:
        tail_session(reader, sid, lines=lines, as_json=as_json)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.command("export")
@click.option("--out", default="autopsy-export.tar.gz", help="Output file path")
@click.option("--format", "fmt", default="tar",
              type=click.Choice(["tar", "json"]),
              help="Export format: tar.gz (default) or legacy JSON")
def cmd_export(out: str, fmt: str) -> None:
    """Export sessions to a tarball or legacy JSON bundle."""
    from autopsy.cli.export_import import export_sessions

    root = _store_root()
    count = export_sessions(root, Path(out), format=fmt)
    console.print(f"[green]exported {count} session(s) to {out}[/green]")


@cli.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
def cmd_import(file: str) -> None:
    """Import sessions from a tarball or legacy JSON bundle."""
    from autopsy.cli.export_import import import_sessions

    root = _store_root()
    count = import_sessions(root, Path(file))
    console.print(f"[green]imported {count} session(s)[/green]")


@cli.command("replay")
@click.argument("session_id")
@click.option("--from-node", "node_id", default=None)
@click.option("--fix", default="Applied developer fix")
@click.option(
    "--live",
    is_flag=True,
    help="Re-import agent module and re-run (requires agent_module_path in session)",
)
@click.option("--json", "as_json", is_flag=True, help="Emit replay result JSON to stdout")
def cmd_replay(session_id: str, node_id: str, fix: str, live: bool, as_json: bool) -> None:
    """Replay a saved session (simulated by default; --live re-runs the agent)."""
    from autopsy.cli.output import replay_result_json
    from autopsy.cli.resolve import resolve_session_id
    from autopsy.core.replay import ReplayEngine

    reader = _bundle_reader()
    sid = resolve_session_id(reader, session_id)
    bundle = reader.load(sid)
    if bundle is None:
        raise click.ClickException(f"session {session_id!r} not found")
    if not node_id:
        for ev in bundle["events"]:
            if ev.get("event_type") == "node_error":
                node_id = ev.get("node_id")
                break
    if not node_id:
        raise click.ClickException(
            "No error node found — pass --from-node NODE_ID")
    engine = ReplayEngine(bundle)
    if live:
        result = asyncio.run(
            engine.live_replay_from_node(node_id),
        )
        if as_json:
            click.echo(replay_result_json(result))
            return
        console.print(f"[green]Live replay OK[/green]: {result.get('result', result)!r}")
        return
    result = engine.simulated_replay(node_id, fix)
    if as_json:
        click.echo(replay_result_json(result))
        return
    comp = result.get("comparison")
    if not comp:
        console.print(result)
        return
    console.print(f"[bold]↻ Replay from {node_id[:8]}[/bold]")
    console.print(f"fix: {fix}\n")
    table = Table(show_header=True)
    table.add_column("metric")
    table.add_column("original")
    table.add_column("replay")
    table.add_column("delta")
    table.add_row("status", comp["original"]["status"],
                  f"[green]{comp['replay']['status']}[/green]", "—")
    table.add_row("errors", str(comp["original"]["errors"]),
                  str(comp["replay"]["errors"]),
                  f"-{comp['original']['errors']-comp['replay']['errors']}")
    table.add_row("duration_ms", f"{int(comp['original']['duration_ms'])}",
                  f"{int(comp['replay']['duration_ms'])}",
                  f"{int(comp['latency_delta_ms'])}")
    table.add_row("tokens", str(comp["original"]["tokens"]),
                  str(comp["replay"]["tokens"]), str(comp["token_delta"]))
    console.print(table)
    console.print(f"[dim]{result['side_effect_warning']}[/dim]")


@cli.command("clean")
@click.option("--all", "all_", is_flag=True, help="Delete all sessions")
def cmd_clean(all_: bool) -> None:
    """Delete saved sessions."""
    from autopsy.core.store.local_fs import LocalFilesystemStore

    root = _store_root()
    sd = root / "sessions"
    if not sd.exists():
        console.print("[dim]nothing to clean[/dim]")
        return
    if not all_:
        console.print(
            "[yellow]Pass --all to confirm deleting every session[/yellow]")
        return
    store = LocalFilesystemStore(root=root)
    count = 0
    for row in list(store.list_sessions()):
        store.delete_session(row["session_id"])
        count += 1
    for entry in list(sd.iterdir()):
        try:
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
                count += 1
            elif entry.suffix == ".json":
                entry.unlink(missing_ok=True)
                count += 1
        except Exception:
            pass
    store.index.clear()
    console.print(f"[green]deleted {count} session(s)[/green]")


@cli.command("deploy")
@click.option("--out", default="autopsy-export.json")
@click.option("--format", "fmt", default="json",
              type=click.Choice(["tar", "json"]),
              hidden=True)
@click.pass_context
def cmd_deploy(ctx: click.Context, out: str, fmt: str) -> None:
    """Deprecated alias for export."""
    console.print(
        "[yellow]Warning: `autopsy deploy` is deprecated — "
        "use `autopsy export` instead.[/yellow]")
    if fmt == "json" or out.endswith(".json"):
        ctx.invoke(cmd_export, out=out, fmt="json")
    else:
        ctx.invoke(cmd_export, out=out, fmt="tar")


if __name__ == "__main__":
    cli()
