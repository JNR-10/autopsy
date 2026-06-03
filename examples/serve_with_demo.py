#!/usr/bin/env python3
"""Run the autopsy dashboard with hackathon demo routes enabled."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("AUTOPSY_DEMO", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.demo_routes import clear_fix_markers, register_demo_routes  # noqa: E402

clear_fix_markers()

from autopsy.server.app import create_app  # noqa: E402
from autopsy.server.ws_manager import ws_manager  # noqa: E402

app = create_app()
register_demo_routes(app, ws_manager)

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("AUTOPSY_PORT", "7823"))
    host = os.environ.get("AUTOPSY_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
