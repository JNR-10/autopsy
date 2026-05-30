"""Demo helpers for hackathon example scripts (not loaded unless AUTOPSY_DEMO=1)."""

from autopsy.demo.routes import (
    clear_fix_markers,
    fix_marker_paths,
    register_demo_routes,
    write_fix_markers,
)

__all__ = [
    "clear_fix_markers",
    "fix_marker_paths",
    "register_demo_routes",
    "write_fix_markers",
]
