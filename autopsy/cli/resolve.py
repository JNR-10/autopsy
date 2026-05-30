"""Session ID resolution for CLI commands."""
from __future__ import annotations

import click

from autopsy.core.compat import LegacyBundleReader


def resolve_session_id(reader: LegacyBundleReader, token: str) -> str:
    """Exact match, else unique prefix. Raises click.ClickException on failure."""
    if reader.load(token) is not None:
        return token

    candidates = [
        s for s in reader.list()
        if s.get("session_id", "").startswith(token)
    ]
    if len(candidates) == 1:
        return candidates[0]["session_id"]
    if len(candidates) > 1:
        ids = [c["session_id"] for c in candidates]
        preview = ", ".join(ids[:5])
        suffix = f" (and {len(ids) - 5} more)" if len(ids) > 5 else ""
        raise click.ClickException(
            f"ambiguous session prefix {token!r}: {len(ids)} matches — "
            f"{preview}{suffix}"
        )
    raise click.ClickException(f"session {token!r} not found")
