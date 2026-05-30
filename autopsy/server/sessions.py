"""Shared session store helpers for server and CLI."""
from __future__ import annotations

from pathlib import Path

from autopsy.core.config import default_session_dir
from autopsy.core.store.local_fs import LocalFilesystemStore


def store_root() -> Path:
    sd = default_session_dir()
    return sd.parent if sd.name == "sessions" else sd


def filesystem_store() -> LocalFilesystemStore:
    return LocalFilesystemStore(root=store_root())


def is_live_session_row(row: dict) -> bool:
    status = row.get("status")
    if status is None:
        status = (row.get("summary") or {}).get("status")
    return status in ("live", "running")
