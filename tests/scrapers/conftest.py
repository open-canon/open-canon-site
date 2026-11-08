"""Shared pytest configuration for the scrapers tests."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip tests marked ``network`` unless ``OPEN_CANON_NETWORK_TESTS=1`` is set.

    Args:
        config: pytest configuration object (unused).
        items: Collected test items; network-marked ones get a skip marker.
    """
    if os.environ.get("OPEN_CANON_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network tests disabled; set OPEN_CANON_NETWORK_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
