from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("OPEN_CANON_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network tests disabled; set OPEN_CANON_NETWORK_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
