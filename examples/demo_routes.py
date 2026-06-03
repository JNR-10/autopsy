"""Hackathon demo routes — not part of the autopsy core package.

Register on a FastAPI app when running examples locally:

    AUTOPSY_DEMO=1 python examples/serve_with_demo.py

Or use: agent-autopsy run --demo (loads this module from the repo checkout).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger("autopsy.examples.demo")


def fix_marker_paths() -> list[Path]:
    home = Path.home() / ".autopsy" / "fix_applied"
    cwd = Path.cwd() / ".autopsy" / "fix_applied"
    return [home, cwd]


def clear_fix_markers() -> None:
    for path in fix_marker_paths():
        try:
            if path.exists():
                path.unlink()
        except Exception:
            logger.debug("could not clear fix marker %s", path)


def write_fix_markers() -> list[str]:
    written: list[str] = []
    for path in fix_marker_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fix applied by dashboard")
            written.append(str(path))
        except (PermissionError, OSError):
            logger.debug("could not write fix marker %s", path)
        except Exception:
            logger.exception("unexpected error writing fix marker %s", path)
    return written


def register_demo_routes(app: FastAPI, ws_manager) -> None:
    @app.post("/api/demo/fix")
    async def demo_apply_fix() -> JSONResponse:
        markers_written = write_fix_markers()
        await ws_manager.broadcast({
            "type": "demo_status",
            "data": {"fix_applied": True, "markers": markers_written},
        })
        return JSONResponse({"fix_applied": True, "markers": markers_written})

    @app.post("/api/demo/reset")
    async def demo_reset() -> JSONResponse:
        removed = []
        for path in fix_marker_paths():
            try:
                if path.exists():
                    path.unlink()
                    removed.append(str(path))
            except Exception:
                logger.exception("could not remove fix marker %s", path)
        await ws_manager.broadcast({
            "type": "demo_status",
            "data": {"fix_applied": False, "removed": removed},
        })
        return JSONResponse({"fix_applied": False, "removed": removed})

    @app.get("/api/demo/status")
    async def demo_status() -> JSONResponse:
        applied = any(p.exists() for p in fix_marker_paths())
        return JSONResponse({"fix_applied": applied})
