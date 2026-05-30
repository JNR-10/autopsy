"""Shape test for the Exporter Protocol."""
from __future__ import annotations

import inspect

from autopsy.core.exporters import Exporter


def test_exporter_has_expected_methods():
    expected = {"export", "finalize_session"}
    members = {n for n, _ in inspect.getmembers(Exporter) if not n.startswith("_")}
    assert expected <= members
