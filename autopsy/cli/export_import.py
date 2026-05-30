"""Export/import sessions as tar.gz (default) or legacy JSON bundle."""
from __future__ import annotations

import json
import tarfile
from pathlib import Path

from autopsy.core.store.local_fs import LocalFilesystemStore


def export_sessions(
    root: Path,
    out_path: Path,
    *,
    format: str = "tar",
) -> int:
    """Export sessions under ``root`` to ``out_path``. Returns session count."""
    sessions_dir = root / "sessions"
    if format == "json":
        from autopsy.core.compat import LegacyBundleReader

        reader = LegacyBundleReader(root=root)
        bundles = []
        for s in reader.list():
            b = reader.load(s["session_id"])
            if b is not None:
                bundles.append(b)
        out_path.write_text(
            json.dumps({"version": "1", "sessions": bundles}, default=str),
        )
        return len(bundles)

    count = 0
    with tarfile.open(out_path, "w:gz") as tar:
        if sessions_dir.exists():
            for entry in sessions_dir.iterdir():
                if entry.is_dir():
                    tar.add(entry, arcname=f"sessions/{entry.name}")
                    count += 1
                elif entry.suffix == ".json":
                    tar.add(entry, arcname=f"sessions/{entry.name}")
                    count += 1
        index_path = root / "index.sqlite"
        if index_path.exists():
            tar.add(index_path, arcname="index.sqlite")
    return count


def import_sessions(root: Path, file_path: Path) -> int:
    """Import sessions from tarball or legacy JSON into ``root``. Returns count."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)

    if file_path.suffix == ".json" or file_path.name.endswith(".json"):
        data = json.loads(file_path.read_text())
        sessions = data.get("sessions", [])
        count = 0
        for bundle in sessions:
            sid = bundle.get("session_id")
            if not sid:
                continue
            dest = root / "sessions" / f"{sid}.json"
            dest.write_text(json.dumps(bundle, default=str))
            count += 1
        store = LocalFilesystemStore(root=root)
        store.reindex()
        return count

    with tarfile.open(file_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in member.name.split("/"):
                continue
            tar.extract(member, root)

    store = LocalFilesystemStore(root=root)
    return store.reindex()
