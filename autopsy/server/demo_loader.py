"""Load hackathon demo routes from examples/ when AUTOPSY_DEMO=1 (not in core wheel)."""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

logger = logging.getLogger("autopsy.server.demo_loader")


def demo_env_enabled() -> bool:
    return os.environ.get("AUTOPSY_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def _demo_module_path() -> Path | None:
    candidates = [
        Path.cwd() / "examples" / "demo_routes.py",
        Path(__file__).resolve().parents[2] / "examples" / "demo_routes.py",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def register_demo_routes_if_env(app) -> bool:
    """Attach /api/demo/* from examples/demo_routes.py. Returns True if registered."""
    if not demo_env_enabled():
        return False
    path = _demo_module_path()
    if path is None:
        logger.warning(
            "autopsy: AUTOPSY_DEMO=1 but examples/demo_routes.py not found "
            "(run from repo root or use examples/serve_with_demo.py)",
        )
        return False
    spec = importlib.util.spec_from_file_location("autopsy_examples_demo_routes", path)
    if spec is None or spec.loader is None:
        return False
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from autopsy.server.ws_manager import ws_manager

    mod.clear_fix_markers()
    mod.register_demo_routes(app, ws_manager)
    return True
